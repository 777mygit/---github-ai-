# 第 6 章：内存管理与 DMA

## 6.1 内核内存分配

### 为什么内核内存分配比用户态复杂

用户态 `malloc` 失败只是当前进程的问题，内核 `kmalloc` 失败可能导致系统功能异常。内核还要处理：
- **物理连续性**：DMA 需要物理连续内存，MMU 无法帮助
- **不能睡眠**：中断上下文分配内存不能等待
- **内存区域**：ISA DMA 只能访问 16MB 以内（ZONE_DMA）

### 常用分配函数

```c
/* kmalloc：小块，物理连续，最常用 */
void *ptr = kmalloc(size, GFP_KERNEL);   /* 进程上下文，可睡眠 */
void *ptr = kmalloc(size, GFP_ATOMIC);   /* 中断上下文，不可睡眠 */
void *ptr = kzalloc(size, GFP_KERNEL);   /* = kmalloc + memset(0) */

/* vmalloc：大块，虚拟连续但物理不连续，不能用于 DMA */
void *ptr = vmalloc(size);

/* 释放 */
kfree(ptr);
vfree(ptr);
```

**`kmalloc` 和 `vmalloc` 如何选择？**

| | kmalloc | vmalloc |
| --- | --- | --- |
| 物理连续 | **是** | 否 |
| 可用于 DMA | **是** | **否** |
| 大小限制 | 通常 ≤4MB | 几乎无限制 |
| 速度 | 快 | 慢（需建页表） |
| 使用场景 | DMA 缓冲、频繁分配 | 大内存、模块加载 |

### GFP 标志

| 标志 | 场景 |
| --- | --- |
| `GFP_KERNEL` | 普通内核分配，可睡眠等待 |
| `GFP_ATOMIC` | 中断/软中断上下文，不可睡眠 |
| `GFP_DMA` | 要求分配在 DMA 区（16MB 以内） |
| `GFP_ZERO` | 分配后清零（等同 kzalloc） |
| `GFP_NOWAIT` | 不睡眠，但也不从紧急池分配 |

---

## 6.2 内核地址空间布局

```
内核虚拟地址空间（32位，以ARM为例）：
0x00000000 ─ 0xBFFFFFFF   用户空间（3GB）
0xC0000000 ─ 0xEFFFFFFF   内核直接映射区（线性映射物理内存）
                           kmalloc 分配在这里，虚拟地址 = 物理地址 + PAGE_OFFSET
0xF0000000 ─ 0xFFBFFFFF   vmalloc 区域
0xFFC00000 ─ ...           固定映射（ioremap、PKmap 等）
```

**`virt_to_phys` 和 `phys_to_virt`**

```c
/* 只对线性映射区（kmalloc 分配的）有效 */
phys_addr_t pa = virt_to_phys(kptr);
void *va = phys_to_virt(pa);

/* ioremap 映射的地址不能用这两个函数 */
```

---

## 6.3 DMA 原理

### 没有 DMA 的数据传输

```
外设（如网卡收到数据包） → 产生中断
CPU 在 ISR 里从 I/O 寄存器逐字节读取数据 → 写到内存
每字节都需要 CPU 参与，传输 1MB 数据 CPU 要介入数百万次
```

### DMA 数据传输

```
外设收到数据 → 触发 DMA 请求（DRQ）
DMA 控制器接管总线，把外设数据直接搬到内存（CPU 全程无需参与）
传输完成 → DMA 产生中断通知 CPU
CPU 只在传输开始和结束各介入一次
```

### Cache 一致性问题

这是 DMA 最容易出 bug 的地方：

```
场景：CPU 写数据到 buf → 数据在 Cache 里，还没写到内存
     DMA 从内存读 buf → 读到的是旧数据！（Cache 未刷新）

场景：DMA 把新数据写到内存 → Cache 里还是旧数据
     CPU 读 buf → 从 Cache 读到的是旧数据！（Cache 未更新）
```

Linux 用 **DMA 一致性内存** 或 **DMA 流式映射** 解决：

---

## 6.4 DMA API

### 一致性 DMA 内存（Coherent DMA）

分配的内存对 CPU 和 DMA 都保持一致（硬件或软件维护一致性），适合长期使用的缓冲区：

```c
#include <linux/dma-mapping.h>

/* 分配一致性 DMA 内存 */
dma_addr_t dma_handle;   /* 设备（总线）地址，给硬件用 */
void *cpu_addr;          /* CPU 虚拟地址，给驱动用 */

cpu_addr = dma_alloc_coherent(dev, size, &dma_handle, GFP_KERNEL);
if (!cpu_addr) return -ENOMEM;

/* 使用：CPU 写 cpu_addr，硬件用 dma_handle */
memcpy(cpu_addr, data, size);
/* 发起 DMA 传输，告诉硬件 dma_handle 和 size */
writel(dma_handle, hw_reg_addr);

/* 释放 */
dma_free_coherent(dev, size, cpu_addr, dma_handle);
```

**为什么要区分 CPU 地址和 DMA 地址？**

有些 SoC 有 IOMMU（I/O MMU），外设看到的地址（总线地址）和 CPU 看到的物理地址不同。`dma_alloc_coherent` 同时返回两种地址，驱动永远用 CPU 地址读写数据，用 DMA 地址配置硬件，不用关心是否有 IOMMU。

### 流式 DMA 映射（Streaming DMA）

适合一次性传输，性能比一致性内存好（不需要禁 Cache）：

```c
/* CPU 准备好数据在 buf */
dma_addr_t dma_addr = dma_map_single(dev, buf, size, DMA_TO_DEVICE);
if (dma_mapping_error(dev, dma_addr)) return -ENOMEM;

/* 必须检查：映射成功后 CPU 不能再访问 buf，直到 unmap */
/* 发起 DMA 写（CPU → 设备）*/
start_dma_transfer(dma_addr, size);
wait_for_dma_complete();

/* 解除映射后 CPU 才能再次访问 buf */
dma_unmap_single(dev, dma_addr, size, DMA_TO_DEVICE);

/* 方向宏 */
/* DMA_TO_DEVICE   : CPU 写到设备（刷新 Cache） */
/* DMA_FROM_DEVICE : 设备写到 CPU（无效化 Cache） */
/* DMA_BIDIRECTIONAL : 双向 */
```

### 散聚 DMA（Scatter-Gather）

一次 DMA 传输跨越多个不连续的内存块，避免把数据先拷到连续缓冲区：

```c
struct scatterlist sg[2];

sg_init_table(sg, 2);
sg_set_buf(&sg[0], buf1, len1);
sg_set_buf(&sg[1], buf2, len2);

int nents = dma_map_sg(dev, sg, 2, DMA_TO_DEVICE);
/* 遍历映射结果，配置硬件 DMA 描述符 */
for_each_sg(sg, s, nents, i) {
    dma_addr_t addr = sg_dma_address(s);
    unsigned int len = sg_dma_len(s);
    /* 填写硬件 DMA 链表 */
}
dma_unmap_sg(dev, sg, 2, DMA_TO_DEVICE);
```

---

## 6.5 mmap 驱动实现

允许用户空间直接映射内核/硬件内存，避免数据拷贝：

```c
static int mydev_mmap(struct file *filp, struct vm_area_struct *vma)
{
    struct mydev_priv *priv = filp->private_data;
    unsigned long size = vma->vm_end - vma->vm_start;

    /* 不允许 mmap 超过缓冲区大小 */
    if (size > priv->buf_size) return -EINVAL;

    /* 禁止缓冲区被换出 */
    vma->vm_flags |= VM_IO | VM_DONTEXPAND | VM_DONTDUMP;
    /* 映射为 uncached（DMA 缓冲）*/
    vma->vm_page_prot = pgprot_noncached(vma->vm_page_prot);

    /* 把 DMA 物理地址映射到用户虚拟地址 */
    if (remap_pfn_range(vma, vma->vm_start,
                        priv->dma_paddr >> PAGE_SHIFT,
                        size, vma->vm_page_prot))
        return -EAGAIN;

    return 0;
}
```

---

## 6.6 面试高频题汇总

**【面试题】DMA 传输完成后为什么要调用 `dma_unmap_single`？**

> `dma_map_single` 把缓冲区的 Cache 处理好（刷新或无效化），并把物理地址记录到 IOMMU 页表。不 unmap 会导致：①IOMMU 映射泄漏；②CPU 读到的数据可能是 Cache 里的旧数据（DMA 写到内存，Cache 未更新）。`dma_unmap_single` 在 `DMA_FROM_DEVICE` 方向时会无效化 Cache，确保 CPU 读到的是 DMA 写入的最新数据。

**【面试题】`kmalloc` 分配的内存能直接给 DMA 用吗？**

> 可以，但要通过 `dma_map_single` 处理 Cache 一致性，不能直接把物理地址给硬件。另外 `kmalloc` 分配的内存是物理连续的，满足大多数 DMA 控制器的要求，但 `vmalloc` 分配的不行（物理不连续）。

**【面试题】为什么 DMA 缓冲区要设为 uncached？**

> 如果 CPU 和 DMA 都能访问 Cache，两者对同一块内存的缓存视图可能不一致（CPU 改了 Cache 但 DMA 从内存读旧值，或 DMA 写了内存但 CPU 从 Cache 读旧值）。把 DMA 缓冲区设为 uncached（`pgprot_noncached`）禁止 CPU 缓存这块内存，所有读写都直接访问内存，从根本上消除一致性问题，代价是 CPU 访问速度变慢。

**【面试题】内核中 `PAGE_SIZE` 通常是多少？有什么意义？**

> 通常是 4096 字节（4KB），ARM64 支持 16KB/64KB 大页。页是内存管理的最小单位，`mmap`、`sbrk` 分配内存都以页为单位。`kmalloc` 对于超过一定大小（通常 ≥PAGE_SIZE）的分配内部也是以页为单位向伙伴系统申请，再从 slab 缓存切分。
