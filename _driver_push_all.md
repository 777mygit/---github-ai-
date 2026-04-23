# Linux 驱动开发大全

> 参考资料：正点原子《I.MX6U 嵌入式 Linux 驱动开发指南》、北京迅为《itop-3568 驱动开发指南》、北京迅为《嵌入式 Linux 开发指南 i.MX6ULL》及 kernel.org 官方文档。

本文档面向有 Linux 应用层基础、希望进入驱动开发领域的工程师。每章从「是什么 → 为什么这样设计 → 怎么写」三个维度展开，配合面试高频题，帮助读者既能写驱动、也能在面试中讲清楚原理。

## 目录

1. 驱动开发基础与内核模块
2. 字符设备驱动
3. 设备树与平台驱动
4. GPIO 与 pinctrl 子系统
5. 中断子系统
6. 内存管理与 DMA
7. I²C 子系统
8. SPI 子系统
9. 输入子系统
10. 网络设备驱动
- 附录 A：常用内核 API 速查
- 附录 B：驱动调试技巧

## 约定

- 代码以 Linux 5.x / 6.x 内核为基准
- 平台示例覆盖 i.MX6ULL（ARM Cortex-A7）和 RK3568（ARM Cortex-A55）
- `[]` 内为可选参数，`<>` 内为必填参数
- 面试题标注 **【面试题】**



---


# 第 1 章：驱动开发基础与内核模块

## 1.1 为什么需要驱动程序

应用程序运行在用户空间，无法直接访问硬件寄存器。原因：

- **安全隔离**：CPU 有特权级（Ring 0 内核态 / Ring 3 用户态），用户态程序直接操作硬件会绕过内核的访问控制，任何程序都能随意读写内存、端口，系统极不稳定。
- **抽象统一**：同一类硬件（如串口）有几十种芯片，驱动把差异屏蔽掉，应用只需 `open/read/write`，不用关心底层寄存器。
- **并发管理**：多个进程可能同时访问同一硬件，驱动负责加锁、排队，保证一致性。

Linux 的解决方案：**驱动运行在内核态**，应用通过系统调用陷入内核，内核调用对应驱动的函数操作硬件，再把结果返回用户态。

```
应用程序 (用户态)
    │  open("/dev/led", O_RDWR)
    │  系统调用 (陷入内核)
    ▼
VFS 虚拟文件系统
    │  根据 inode 找到 file_operations
    ▼
字符/块/网络 驱动
    │  操作寄存器
    ▼
硬件 (LED / UART / 网卡 ...)
```

**【面试题】用户空间和内核空间为什么要隔离？**

> CPU 的 MMU（内存管理单元）通过页表给每个进程建立独立的虚拟地址空间，并用特权级位控制哪些指令/地址只有内核才能执行/访问。隔离的目的是：①防止用户程序破坏内核数据；②防止一个进程访问另一个进程的内存；③强制所有硬件访问通过驱动，保证安全可控。

---

## 1.2 内核模块基础

### 为什么要有内核模块

如果把所有驱动都编译进内核（Built-in），内核会很大，启动慢，且每次修改驱动都要重新编译整个内核。

**内核模块（Kernel Module / .ko 文件）** 是可以在运行时动态加载/卸载的内核代码片段，解决了：
- 按需加载：不用的驱动不占内存
- 开发迭代快：改驱动不用重启，`rmmod → insmod` 即可

### 最小内核模块

```c
#include <linux/module.h>
#include <linux/init.h>

/* 模块加载时调用，对应 insmod */
static int __init hello_init(void)
{
    printk(KERN_INFO "hello: module loaded\n");
    return 0;   /* 返回非 0 表示加载失败 */
}

/* 模块卸载时调用，对应 rmmod */
static void __exit hello_exit(void)
{
    printk(KERN_INFO "hello: module unloaded\n");
}

module_init(hello_init);
module_exit(hello_exit);

MODULE_LICENSE("GPL");          /* 必须声明，否则加载时有 taint 警告 */
MODULE_AUTHOR("yourname");
MODULE_DESCRIPTION("hello world driver");
```

### 为什么用 `printk` 而不是 `printf`

`printf` 是 C 库函数，依赖用户态的 `glibc`，内核里没有 `glibc`。`printk` 是内核自己实现的，直接写到内核日志缓冲区（ring buffer），通过 `dmesg` 命令查看。

日志级别（数字越小越紧急）：

| 宏 | 数值 | 场景 |
| --- | --- | --- |
| `KERN_EMERG` | 0 | 系统不可用 |
| `KERN_ALERT` | 1 | 必须立即处理 |
| `KERN_CRIT` | 2 | 严重错误 |
| `KERN_ERR` | 3 | 一般错误 |
| `KERN_WARNING` | 4 | 警告 |
| `KERN_NOTICE` | 5 | 普通但重要 |
| `KERN_INFO` | 6 | 信息（开发常用） |
| `KERN_DEBUG` | 7 | 调试（需开启） |

### Makefile 编写

```makefile
# 模块名（生成 hello.ko）
obj-m := hello.o

# 内核源码路径（交叉编译时换成目标板内核路径）
KDIR := /lib/modules/$(shell uname -r)/build

PWD := $(shell pwd)

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
```

**为什么要指定 `KDIR`？**

内核模块的编译需要内核的头文件和 `Kbuild` 系统，`-C $(KDIR)` 让 make 切换到内核目录使用内核的 Makefile，`M=$(PWD)` 告诉内核 Makefile 在哪里找模块源码。

### 交叉编译

```makefile
# 针对 ARM（i.MX6ULL / RK3568）
CROSS_COMPILE ?= arm-linux-gnueabihf-
ARCH          ?= arm
KDIR          := /home/user/linux-5.4   # 目标板内核源码

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules \
	    ARCH=$(ARCH) CROSS_COMPILE=$(CROSS_COMPILE)
```

### 常用命令

```bash
insmod hello.ko           # 加载模块
rmmod hello               # 卸载模块（不带 .ko）
lsmod                     # 查看已加载模块
modinfo hello.ko          # 查看模块信息
dmesg | tail -20          # 查看最新内核日志
dmesg -C                  # 清空日志
```

---

## 1.3 模块参数与符号导出

### 模块参数

允许 `insmod` 时传参，类似命令行参数：

```c
static int debug = 0;
static char *name = "default";

module_param(debug, int, 0644);   /* 参数名, 类型, sysfs 权限 */
module_param(name, charp, 0444);
MODULE_PARM_DESC(debug, "enable debug output (default=0)");

/* 使用：insmod hello.ko debug=1 name=mydev */
```

### 符号导出（EXPORT_SYMBOL）

内核模块之间可以调用彼此的函数，但被调用方必须显式导出符号：

```c
/* 在模块 A 中 */
int my_add(int a, int b) { return a + b; }
EXPORT_SYMBOL(my_add);              /* 普通导出，任何模块可用 */
EXPORT_SYMBOL_GPL(my_add);         /* 只有 GPL 模块可用 */
```

**为什么要 `EXPORT_SYMBOL_GPL`？**

Linux 内核是 GPL 许可证。如果你的驱动用了 GPL 专属接口，则驱动也必须是 GPL 的，否则会有法律问题。这是内核社区保护开放源码的技术手段。

---

## 1.4 内核模块与应用程序的关键区别

| 对比项 | 应用程序 | 内核模块 |
| --- | --- | --- |
| 运行空间 | 用户态 | 内核态 |
| 入口函数 | `main()` | `module_init()` 指定的函数 |
| 库函数 | glibc（printf、malloc...） | 内核 API（printk、kmalloc...） |
| 错误后果 | 进程崩溃，不影响其他进程 | 内核 panic，整机宕机 |
| 编译方式 | gcc 直接编译链接 | 依赖内核 Kbuild 系统 |
| 内存访问 | 虚拟地址，受 MMU 保护 | 可访问所有物理地址 |
| 浮点运算 | 可以 | 默认**禁用**（需手动保存 FPU 上下文） |

**【面试题】内核模块里能用 malloc 吗？为什么？**

> 不能。`malloc` 是 glibc 提供的，依赖用户态的堆管理和系统调用。内核里没有 glibc，内存分配用 `kmalloc`（小块，物理连续）、`vmalloc`（大块，虚拟连续但物理不连续）或 `kzalloc`（kmalloc + 清零）。

**【面试题】内核模块和内核的关系是什么？**

> 内核模块是内核的一部分，加载后运行在内核空间，与内核共享同一地址空间。模块可以调用内核导出的任何函数，也可以修改内核数据结构。这就是为什么内核模块的 bug 会导致整个系统崩溃，而用户态程序的 bug 只影响自己。

---

## 1.5 内核版本兼容与 Kconfig

### 版本兼容宏

```c
#include <linux/version.h>

#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 6, 0)
    /* 5.6+ 的新 API */
#else
    /* 旧版 API */
#endif
```

### Kconfig 与 menuconfig

大型驱动通常集成进内核，用 `Kconfig` 声明配置项：

```kconfig
config MY_LED_DRIVER
    tristate "My LED Driver"
    depends on GPIO_GENERIC
    help
      选 Y 编译进内核，选 M 编译为模块，选 N 不编译。
```

`tristate` 三态：Y（built-in）/ M（module）/ N（disabled），这就是驱动为什么既能编译进内核也能做成 .ko 的原因。

---

## 1.6 面试高频题汇总

**【面试题】ko 文件是什么格式？**

> ELF（Executable and Linkable Format）格式，但不是完整可执行文件，是可重定位目标文件（Relocatable Object）。加载时内核动态链接，把符号地址填入。

**【面试题】insmod 和 modprobe 有什么区别？**

> `insmod` 直接加载指定的 .ko 文件，不处理依赖。`modprobe` 会读取 `/lib/modules/$(uname -r)/modules.dep` 自动按依赖顺序加载所有依赖模块，更智能，推荐生产环境使用。

**【面试题】内核模块的 init 函数返回非 0 会怎样？**

> `insmod` 失败，返回错误码（负值），模块不会被加载，不会调用 exit 函数。内核日志会打印错误信息。

**【面试题】MODULE_LICENSE 必须写吗？写错了会怎样？**

> 技术上不强制，但不写或写非 GPL 许可证时，加载模块后内核会被标记为「tainted」（污染），这会影响内核开发者接受 bug 报告，同时无法使用 EXPORT_SYMBOL_GPL 导出的接口。

**【面试题】内核模块能创建线程吗？**

> 可以，使用 `kthread_create()` + `wake_up_process()` 或 `kthread_run()`。内核线程运行在内核空间，没有用户地址空间，常用于处理异步任务（如驱动的轮询、后台处理）。



---


# 第 2 章：字符设备驱动

## 2.1 字符设备是什么，为什么这样分类

Linux 把设备分为三类：

| 类型 | 特征 | 例子 |
| --- | --- | --- |
| 字符设备（char） | 以字节流方式顺序访问，无缓冲 | LED、串口、传感器、摄像头 |
| 块设备（block） | 以固定大小块随机访问，有缓冲 | 硬盘、SD 卡、eMMC |
| 网络设备（net） | 面向数据包，不通过文件系统访问 | 以太网、WiFi |

**为什么字符设备不加缓冲？**

串口读到一个字节就要处理，GPIO 的电平变化要实时响应，缓冲反而引入延迟。而块设备（磁盘）读一个字节也要读整个扇区（512B），缓冲能大幅提高效率。

字符设备通过 `/dev/xxx` 文件访问，应用层的 `open/read/write/ioctl` 直接映射到驱动里的对应函数。

---

## 2.2 设备号：内核如何找到驱动

每个字符设备有一个 **设备号**，由主设备号（Major）和次设备号（Minor）组成，打包成 32 位的 `dev_t`：

```
dev_t = Major(12位) | Minor(20位)
```

- **主设备号**：标识驱动类型，同一个驱动的所有设备共享同一主设备号
- **次设备号**：区分同一驱动管理的多个设备（如 `/dev/ttyS0`、`/dev/ttyS1`）

```bash
ls -l /dev/ttyS0
# crw-rw---- 1 root dialout 4, 64 ...
#                            ^  ^
#                          主号 次号
```

**为什么这样设计？**

内核维护一张字符设备表，以主设备号为索引找到 `file_operations`。次设备号留给驱动自己用，可以区分硬件实例。这样内核只需要一张简单的表，驱动内部自己管理多个设备。

### 申请设备号

```c
/* 方法1：静态分配（自己指定主设备号，容易冲突） */
int major = register_chrdev_region(MKDEV(200, 0), 1, "myled");

/* 方法2：动态分配（推荐，内核自动找空闲的主设备号） */
dev_t devno;
alloc_chrdev_region(&devno, 0, 1, "myled");
int major = MAJOR(devno);
int minor = MINOR(devno);

/* 释放 */
unregister_chrdev_region(devno, 1);
```

**【面试题】为什么推荐动态分配设备号？**

> 静态分配需要查阅 `Documentation/admin-guide/devices.txt` 找空闲号，容易和其他驱动冲突，而且不同内核版本空闲号不同。动态分配由内核保证唯一性，是现代驱动的标准做法。

---

## 2.3 file_operations：驱动的"函数表"

`file_operations` 结构体是字符驱动的核心，它把 VFS 的通用操作（open/read/write...）和驱动的具体实现挂钩：

```c
static const struct file_operations myled_fops = {
    .owner   = THIS_MODULE,
    .open    = myled_open,
    .release = myled_release,   /* close 时调用 */
    .read    = myled_read,
    .write   = myled_write,
    .unlocked_ioctl = myled_ioctl,
};
```

**`.owner = THIS_MODULE` 是什么作用？**

防止驱动被 `rmmod` 卸载时还有文件描述符在使用它。设置 `owner` 后，当有进程打开了这个设备，内核会增加模块的引用计数，`rmmod` 会失败并提示「Device or resource busy」，等所有文件关闭后才能卸载。

---

## 2.4 完整字符驱动：LED 控制

### 硬件操作（直接映射寄存器）

以 i.MX6ULL 为例，GPIO1_IO03 控制 LED：

```c
#include <linux/module.h>
#include <linux/fs.h>
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/uaccess.h>
#include <linux/io.h>

#define LED_ON  1
#define LED_OFF 0

/* 寄存器物理地址（i.MX6ULL GPIO1） */
#define CCM_CCGR1_BASE      (0x020C406C)
#define SW_MUX_GPIO1_IO03   (0x020E0068)
#define SW_PAD_GPIO1_IO03   (0x020E02F4)
#define GPIO1_DR            (0x0209C000)
#define GPIO1_GDIR          (0x0209C004)

static void __iomem *CCM_CCGR1;
static void __iomem *SW_MUX;
static void __iomem *SW_PAD;
static void __iomem *GPIO1_DR_reg;
static void __iomem *GPIO1_GDIR_reg;

static void led_switch(int status)
{
    u32 val;
    val = readl(GPIO1_DR_reg);
    if (status == LED_ON)
        val &= ~(1 << 3);   /* 低电平点亮 */
    else
        val |= (1 << 3);
    writel(val, GPIO1_DR_reg);
}
```

**为什么用 `ioremap` 而不是直接用物理地址？**

内核运行在虚拟地址空间，MMU 开启后物理地址不能直接访问。`ioremap` 把物理地址映射到内核虚拟地址空间，才能用指针访问。`readl/writel` 保证内存屏障，防止编译器或 CPU 乱序优化寄存器访问。

```c
/* 初始化：ioremap 映射寄存器 */
static int led_hw_init(void)
{
    CCM_CCGR1    = ioremap(CCM_CCGR1_BASE, 4);
    SW_MUX       = ioremap(SW_MUX_GPIO1_IO03, 4);
    SW_PAD       = ioremap(SW_PAD_GPIO1_IO03, 4);
    GPIO1_DR_reg = ioremap(GPIO1_DR, 4);
    GPIO1_GDIR_reg = ioremap(GPIO1_GDIR, 4);

    /* 使能 GPIO1 时钟 */
    writel(readl(CCM_CCGR1) | (3 << 26), CCM_CCGR1);
    /* 复用为 GPIO */
    writel(5, SW_MUX);
    /* 设置为输出 */
    writel(readl(GPIO1_GDIR_reg) | (1 << 3), GPIO1_GDIR_reg);
    /* 默认关闭 */
    led_switch(LED_OFF);
    return 0;
}

static void led_hw_exit(void)
{
    iounmap(CCM_CCGR1);
    iounmap(SW_MUX);
    iounmap(SW_PAD);
    iounmap(GPIO1_DR_reg);
    iounmap(GPIO1_GDIR_reg);
}
```

### cdev 注册

```c
static dev_t   led_devno;
static struct cdev led_cdev;
static struct class  *led_class;
static struct device *led_device;

static int myled_open(struct inode *inode, struct file *filp)
{
    return 0;
}

static int myled_release(struct inode *inode, struct file *filp)
{
    return 0;
}

/* 应用 write(fd, &val, 1) 控制 LED */
static ssize_t myled_write(struct file *filp, const char __user *buf,
                           size_t count, loff_t *ppos)
{
    int ret;
    u8 val;

    ret = copy_from_user(&val, buf, 1);  /* 从用户空间拷贝数据 */
    if (ret < 0)
        return -EFAULT;

    led_switch(val ? LED_ON : LED_OFF);
    return 1;
}

static const struct file_operations led_fops = {
    .owner   = THIS_MODULE,
    .open    = myled_open,
    .release = myled_release,
    .write   = myled_write,
};

static int __init led_init(void)
{
    int ret;

    /* 1. 申请设备号 */
    ret = alloc_chrdev_region(&led_devno, 0, 1, "led");
    if (ret < 0) return ret;

    /* 2. 初始化并注册 cdev */
    cdev_init(&led_cdev, &led_fops);
    led_cdev.owner = THIS_MODULE;
    ret = cdev_add(&led_cdev, led_devno, 1);
    if (ret < 0) goto err_cdev;

    /* 3. 创建 /sys/class/led 和 /dev/led（自动 mknod） */
    led_class = class_create(THIS_MODULE, "led");
    if (IS_ERR(led_class)) { ret = PTR_ERR(led_class); goto err_class; }

    led_device = device_create(led_class, NULL, led_devno, NULL, "led");
    if (IS_ERR(led_device)) { ret = PTR_ERR(led_device); goto err_device; }

    /* 4. 初始化硬件 */
    ret = led_hw_init();
    if (ret) goto err_hw;

    printk(KERN_INFO "led: driver loaded, major=%d\n", MAJOR(led_devno));
    return 0;

err_hw:     device_destroy(led_class, led_devno);
err_device: class_destroy(led_class);
err_class:  cdev_del(&led_cdev);
err_cdev:   unregister_chrdev_region(led_devno, 1);
    return ret;
}

static void __exit led_exit(void)
{
    led_hw_exit();
    device_destroy(led_class, led_devno);
    class_destroy(led_class);
    cdev_del(&led_cdev);
    unregister_chrdev_region(led_devno, 1);
    printk(KERN_INFO "led: driver unloaded\n");
}

module_init(led_init);
module_exit(led_exit);
MODULE_LICENSE("GPL");
```

**为什么要 `class_create` + `device_create`？**

`cdev_add` 只是在内核内部注册了字符设备，`/dev/` 下还没有设备节点。手动执行 `mknod /dev/led c 主号 次号` 太麻烦。`class_create` 在 `/sys/class/` 下创建类目录，`device_create` 触发 `udev`（或 `mdev`）自动创建 `/dev/led` 节点，驱动加载即可用。

---

## 2.5 用户态访问与数据拷贝

**为什么不能用 `memcpy` 直接拷贝用户数据？**

用户空间指针在内核里可能：
- 指向无效地址（用户程序 bug）
- 触发缺页中断（需要换页）
- 是恶意构造的内核地址（安全攻击）

`copy_from_user` / `copy_to_user` 做了地址合法性检查和安全处理，是跨越内核/用户边界传数据的唯一正确方式。

```c
/* 从用户空间读数据到内核 */
unsigned long copy_from_user(void *to, const void __user *from, unsigned long n);

/* 从内核写数据到用户空间 */
unsigned long copy_to_user(void __user *to, const void *from, unsigned long n);
/* 返回值：0=成功，非0=未拷贝的字节数 */

/* 单个简单类型的快速版本 */
get_user(val, ptr);     /* 相当于 val = *ptr（带检查） */
put_user(val, ptr);     /* 相当于 *ptr = val（带检查） */
```

---

## 2.6 ioctl：设备控制命令

`read/write` 只能传数据，控制命令（如设置波特率、查询状态）用 `ioctl`：

```c
/* 命令号构造宏（防止不同驱动命令号冲突） */
/* _IO(type, nr)         无数据传输 */
/* _IOR(type, nr, size)  内核→用户 */
/* _IOW(type, nr, size)  用户→内核 */
/* _IOWR(type, nr, size) 双向 */

#define LED_MAGIC   'L'
#define LED_ON_CMD  _IO(LED_MAGIC, 0)
#define LED_OFF_CMD _IO(LED_MAGIC, 1)
#define LED_GET_CMD _IOR(LED_MAGIC, 2, int)

static long myled_ioctl(struct file *filp, unsigned int cmd, unsigned long arg)
{
    int status;
    switch (cmd) {
    case LED_ON_CMD:
        led_switch(LED_ON);
        break;
    case LED_OFF_CMD:
        led_switch(LED_OFF);
        break;
    case LED_GET_CMD:
        status = led_get_status();
        if (copy_to_user((int __user *)arg, &status, sizeof(int)))
            return -EFAULT;
        break;
    default:
        return -EINVAL;
    }
    return 0;
}
```

**【面试题】ioctl 的命令号为什么要用宏构造，不能自己随便定义？**

> 命令号包含类型（type/magic，8bit）、序号（nr，8bit）、数据方向（dir，2bit）、数据大小（size，14bit）。宏构造保证了不同驱动之间命令号不冲突（magic 不同），内核可以根据方向位做安全检查，用户态也能通过命令号知道需要传多大的数据。

---

## 2.7 面试高频题汇总

**【面试题】字符驱动的注册流程？**

> ①`alloc_chrdev_region` 申请设备号 → ②`cdev_init` 初始化 cdev，绑定 `file_operations` → ③`cdev_add` 注册到内核 → ④`class_create` + `device_create` 自动创建 `/dev/` 节点。卸载时反向操作。

**【面试题】`open` 时内核如何找到对应驱动的 `file_operations`？**

> 打开 `/dev/led` 时，VFS 读取该文件的 inode，inode 里存有设备号（主+次），内核以主设备号为键在字符设备表（`cdev_map`）中查找对应的 `cdev`，从 `cdev` 拿到 `file_operations`，后续所有操作都用这个函数表。

**【面试题】`read` 返回 0 代表什么？**

> 返回 0 表示到达文件末尾（EOF），应用层的 `read` 会收到 0，通常会停止读取。驱动里如果没有数据可读应该返回 0（而不是阻塞或返回错误），让应用感知到「没有更多数据」。

**【面试题】`ioctl` 和 `read/write` 如何选择？**

> 传大块数据用 `read/write`（效率高，可用 splice/sendfile 零拷贝）；设备控制、查询状态、传小参数用 `ioctl`（语义清晰，每个命令有独立含义）。不要用 `write` 传控制命令，会让驱动逻辑复杂且难维护。

**【面试题】什么是 `__user` 标记？**

> 这是 `sparse` 静态检查工具用的注解，标记该指针来自用户空间。如果你把内核指针传给期望 `__user` 指针的函数（或反过来），`sparse` 会报警告。运行时没有影响，是编译期静态分析的辅助手段，用于提前发现内核/用户指针混用的 bug。



---


# 第 3 章：设备树与平台驱动

## 3.1 为什么需要设备树

ARM Linux 3.x 之前，板级硬件信息（哪个 GPIO 接 LED、哪个 I2C 地址接传感器）全部硬编码在 `arch/arm/mach-xxx/` 下的 C 文件里。每款板子一个文件，内核里积累了几千个板文件，Linus Torvalds 忍无可忍，把 PowerPC 已有的 **Device Tree（设备树）** 机制引入 ARM。

**设备树解决了什么问题？**

- 把板级硬件描述从内核代码中剥离，写成独立的 `.dts` 文件
- 内核二进制不变，换板子只换 `.dtb` 文件
- 驱动通过设备树获取引脚、地址、中断号，不再硬编码
- 一个内核镜像支持多个不同板子（同 SoC 系列）

```
之前：板级信息 → 内核 C 文件 → 编译进 vmlinux
之后：板级信息 → .dts → dtc 编译 → .dtb → uboot 传给内核
```

---

## 3.2 设备树语法

### 基本结构

```dts
/dts-v1/;

/ {                             /* 根节点 */
    model = "My i.MX6ULL Board";
    compatible = "fsl,imx6ull-14x14-evk", "fsl,imx6ull";

    cpus {
        cpu@0 {
            compatible = "arm,cortex-a7";
            reg = <0>;          /* CPU 编号 */
        };
    };

    memory@80000000 {
        device_type = "memory";
        reg = <0x80000000 0x20000000>;  /* 起始地址 + 大小 */
    };

    /* 用户自定义节点 */
    myled {
        compatible = "mycompany,myled";
        gpios = <&gpio1 3 GPIO_ACTIVE_LOW>;
        status = "okay";
    };
};
```

### 核心属性

| 属性 | 含义 | 示例 |
| --- | --- | --- |
| `compatible` | 驱动匹配字符串，格式 "厂商,型号" | `"fsl,imx6ul-gpio"` |
| `reg` | 寄存器基地址和大小 | `<0x0209C000 0x4000>` |
| `interrupts` | 中断号和触发类型 | `<GIC_SPI 66 IRQ_TYPE_LEVEL_HIGH>` |
| `clocks` | 时钟引用 | `<&clks IMX6UL_CLK_GPIO1>` |
| `status` | 节点状态 | `"okay"` / `"disabled"` |
| `#address-cells` | 子节点 reg 地址占几个 u32 | `<1>` |
| `#size-cells` | 子节点 reg 大小占几个 u32 | `<1>` |

### include 与 overlay

```dts
/* imx6ull.dtsi：SoC 级描述（厂商提供） */
#include "imx6ull.dtsi"

/* myboard.dts：板级描述（用户编写） */
&gpio1 {
    status = "okay";    /* 覆写 dtsi 里的 disabled */
};

&i2c1 {
    clock-frequency = <100000>;
    status = "okay";

    /* 在 I2C1 总线上挂载传感器 */
    mpu6050@68 {
        compatible = "invensense,mpu6050";
        reg = <0x68>;
        interrupt-parent = <&gpio1>;
        interrupts = <2 IRQ_TYPE_EDGE_FALLING>;
    };
};
```

**【面试题】`compatible` 属性的匹配规则是什么？**

> `compatible` 是字符串列表，从左到右依次匹配。内核先尝试精确匹配（厂商+型号），若找不到驱动再匹配更通用的字符串。例如 `"fsl,imx6ul-gpio", "fsl,imx35-gpio"` 先找 `imx6ul-gpio` 驱动，找不到再找 `imx35-gpio` 驱动，实现了向后兼容。

---

## 3.3 平台设备与平台驱动

### 为什么要有 platform 总线

I2C、SPI 有物理总线，设备插上去后总线控制器能扫描到。但 SoC 片上外设（GPIO、UART、定时器）直接内存映射，没有物理总线，内核需要一种虚拟总线来统一管理它们——这就是 **platform 总线**。

```
platform 总线
├── platform_device（设备端，描述硬件资源）
└── platform_driver（驱动端，实现功能）
        匹配成功 → probe() 被调用
```

**匹配过程**：
1. `platform_driver_register` 注册驱动
2. platform 总线遍历所有已注册的 `platform_device`
3. 比较 `device.compatible` 和 `driver.of_match_table` 中的字符串
4. 匹配成功，调用 `driver.probe()`

### platform_driver 框架

```c
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/of_gpio.h>

struct myled_priv {
    int gpio;               /* GPIO 编号 */
    struct cdev cdev;
    dev_t devno;
    struct class *class;
};

/* 设备树匹配表 */
static const struct of_device_id myled_of_match[] = {
    { .compatible = "mycompany,myled" },
    { /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, myled_of_match);

/* probe：设备树节点和驱动匹配后调用 */
static int myled_probe(struct platform_device *pdev)
{
    struct myled_priv *priv;
    int ret;

    /* 分配私有数据，绑定到设备（自动随设备销毁） */
    priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
    if (!priv)
        return -ENOMEM;
    platform_set_drvdata(pdev, priv);

    /* 从设备树获取 GPIO */
    priv->gpio = of_get_named_gpio(pdev->dev.of_node, "gpios", 0);
    if (priv->gpio < 0) {
        dev_err(&pdev->dev, "failed to get gpio\n");
        return priv->gpio;
    }

    /* 申请 GPIO（devm_ 版本：模块卸载时自动释放） */
    ret = devm_gpio_request_one(&pdev->dev, priv->gpio,
                                GPIOF_OUT_INIT_HIGH, "myled");
    if (ret) return ret;

    /* 注册字符设备（略，同第2章） */
    dev_info(&pdev->dev, "myled probed, gpio=%d\n", priv->gpio);
    return 0;
}

static int myled_remove(struct platform_device *pdev)
{
    /* devm_ 申请的资源自动释放，这里只做驱动逻辑清理 */
    dev_info(&pdev->dev, "myled removed\n");
    return 0;
}

static struct platform_driver myled_driver = {
    .probe  = myled_probe,
    .remove = myled_remove,
    .driver = {
        .name           = "myled",
        .of_match_table = myled_of_match,
    },
};

module_platform_driver(myled_driver);   /* 宏替代手写 init/exit */
MODULE_LICENSE("GPL");
```

**`devm_` 前缀的作用是什么？**

`devm_`（device managed）系列函数申请的资源会绑定到 `struct device`，当设备从总线上移除时（`remove` 调用后），内核自动释放这些资源。好处：不需要在 `remove` 里写一堆对称的释放代码，不容易泄漏资源，代码更简洁。

---

## 3.4 从设备树获取资源

### 常用 of_xxx API

```c
struct device_node *np = pdev->dev.of_node;

/* 读取整数属性 */
u32 val;
of_property_read_u32(np, "clock-frequency", &val);

/* 读取字符串属性 */
const char *str;
of_property_read_string(np, "label", &str);

/* 获取 GPIO */
int gpio = of_get_named_gpio(np, "gpios", 0);

/* 获取 IRQ */
int irq = platform_get_irq(pdev, 0);

/* 获取寄存器地址并 ioremap（devm 版） */
void __iomem *base = devm_platform_ioremap_resource(pdev, 0);

/* 获取时钟 */
struct clk *clk = devm_clk_get(&pdev->dev, "uart");
clk_prepare_enable(clk);
```

### platform_device 资源（非设备树方式，老内核兼容）

```c
/* board 文件里定义资源 */
static struct resource myled_resources[] = {
    [0] = DEFINE_RES_MEM(0x0209C000, 0x4000),   /* 寄存器 */
    [1] = DEFINE_RES_IRQ(79),                    /* 中断 */
};

/* 驱动里获取 */
struct resource *res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
void __iomem *base = devm_ioremap_resource(&pdev->dev, res);
```

---

## 3.5 设备树调试

```bash
# 查看已解析的设备树（运行时）
ls /proc/device-tree/

# 查看某节点属性
cat /proc/device-tree/myled/compatible

# 用 dtc 反编译 dtb
dtc -I dtb -O dts -o out.dts /boot/dtb/imx6ull-board.dtb

# 查看 platform 总线已注册设备
ls /sys/bus/platform/devices/

# 查看驱动绑定情况
cat /sys/bus/platform/drivers/myled/uevent
```

---

## 3.6 面试高频题汇总

**【面试题】设备树是在什么时候被解析的？**

> uboot 把 `.dtb` 文件加载到内存，通过寄存器（r2）把 dtb 地址传给内核。内核启动早期（`setup_arch()`）调用 `unflatten_device_tree()` 把二进制 dtb 解析成 `device_node` 树形链表，存在内存里，之后驱动通过 `of_xxx` API 访问。

**【面试题】platform_driver 的 probe 什么时候被调用？**

> 两种情况：①注册驱动时，总线遍历已有设备找到匹配就调用；②注册设备时，总线遍历已有驱动找到匹配就调用。实际上是总线的 `match` 函数触发 `really_probe`，最终调用 `driver.probe`。

**【面试题】`compatible` 匹配失败会怎样？**

> 驱动注册成功，但没有设备与之匹配，`probe` 不被调用。`/dev/` 下不会有设备节点，功能不可用，但内核不会报错（警告级别）。可以通过 `dmesg` 看是否有「no driver found」的信息。

**【面试题】设备树里的 `status = "disabled"` 有什么用？**

> 被禁用的节点内核不会为其创建 `platform_device`，驱动的 `probe` 不会被调用。常用于在 `dtsi`（SoC 级）里默认禁用所有外设，在 `dts`（板级）里按需覆写为 `"okay"`，实现一个 dtsi 支持多种板子配置。

**【面试题】`devm_kzalloc` 和 `kzalloc` 的区别？**

> 两者都分配内核内存并清零（k=kmalloc, z=zeroed）。区别是 `devm_kzalloc` 把内存绑定到 `struct device`，设备被 remove 时自动调用 `kfree`。`kzalloc` 需要手动在对称位置 `kfree`，容易遗漏造成内存泄漏。现代驱动优先用 `devm_` 系列。



---


# 第 4 章：GPIO 与 pinctrl 子系统

## 4.1 为什么要有 pinctrl 子系统

SoC 的引脚是复用的：同一个物理引脚可以配置为 GPIO、UART TX、I2C SCL 等多种功能。以 i.MX6ULL 为例，一个引脚有 8 种复用选项（ALT0～ALT7）。

**没有 pinctrl 之前的问题：**
- 每个驱动各自操作复用寄存器，互相冲突，无法统一管理
- 同一引脚被多个驱动同时声明，运行时才发现冲突

**pinctrl 子系统的作用：**
- 统一管理所有引脚的复用（mux）和电气属性（驱动强度、上下拉）
- 驱动在设备树里声明「我要用哪些引脚、配成什么功能」，由 pinctrl 核心统一仲裁
- 驱动 probe 时自动配置引脚，remove 时自动释放

---

## 4.2 设备树中的 pinctrl 配置

### SoC 级 pinctrl 节点（dtsi 里）

```dts
/* i.MX6ULL 的 iomuxc 控制器 */
iomuxc: iomuxc@020e0000 {
    compatible = "fsl,imx6ul-iomuxc";
    reg = <0x020e0000 0x4000>;
};
```

### 板级引脚组配置（dts 里）

```dts
&iomuxc {
    pinctrl_myled: myled-grp {
        fsl,pins = <
            /* MX6UL_PAD_GPIO1_IO03 → GPIO1_IO03, ALT5, 电气属性 */
            MX6UL_PAD_GPIO1_IO03__GPIO1_IO03  0x10b0
        >;
        /* 0x10b0 含义：
         * bit[16]:   HYS = 0（关闭迟滞）
         * bit[15:14]: PUS = 00（下拉100k）
         * bit[13]:   PUE = 1（pull）
         * bit[12]:   PKE = 0（关闭 keeper）
         * bit[11]:   ODE = 0（非开漏）
         * bit[5:3]:  SPEED = 010（100MHz）
         * bit[2:0]:  DSE = 110（R0/6，47Ω） */
    };

    pinctrl_uart1: uart1-grp {
        fsl,pins = <
            MX6UL_PAD_UART1_TX_DATA__UART1_DCE_TX  0x1b0b1
            MX6UL_PAD_UART1_RX_DATA__UART1_DCE_RX  0x1b0b1
        >;
    };
};
```

### 设备节点引用 pinctrl

```dts
myled {
    compatible = "mycompany,myled";
    pinctrl-names = "default", "sleep";   /* 状态名 */
    pinctrl-0 = <&pinctrl_myled>;         /* default 状态使用的引脚组 */
    pinctrl-1 = <&pinctrl_myled_sleep>;   /* sleep 状态（可选） */
    gpios = <&gpio1 3 GPIO_ACTIVE_LOW>;
    status = "okay";
};
```

---

## 4.3 GPIO 子系统

### GPIO 编号计算

```
gpio_num = gpio_bank * 32 + gpio_bit
GPIO1_IO03 = 0 * 32 + 3 = 3
GPIO3_IO18 = 2 * 32 + 18 = 82
```

### 驱动中使用 GPIO API

```c
#include <linux/gpio.h>
#include <linux/of_gpio.h>

/* 从设备树获取 GPIO 编号 */
int gpio = of_get_named_gpio(np, "gpios", 0);
if (!gpio_is_valid(gpio)) return -EINVAL;

/* 申请 GPIO（devm 版，自动释放） */
ret = devm_gpio_request_one(&pdev->dev, gpio,
                            GPIOF_OUT_INIT_HIGH, "myled");

/* 操作 GPIO */
gpio_set_value(gpio, 1);        /* 输出高 */
gpio_set_value(gpio, 0);        /* 输出低 */
int val = gpio_get_value(gpio); /* 读输入 */
gpio_direction_output(gpio, 1); /* 设为输出 */
gpio_direction_input(gpio);     /* 设为输入 */
```

### 新版 gpiod API（推荐）

老的 `gpio_xxx` API 需要计算绝对 GPIO 编号，不够优雅。新版 `gpiod` API 直接从设备树描述符获取：

```c
#include <linux/gpio/consumer.h>

/* 获取 GPIO 描述符（自动处理极性、pinctrl） */
struct gpio_desc *gpiod;
gpiod = devm_gpiod_get(&pdev->dev, NULL, GPIOD_OUT_HIGH);
/* 设备树里 gpios 属性，gpiod 自动处理 GPIO_ACTIVE_LOW 极性 */

/* 操作（极性自动处理，不用关心硬件高/低电平） */
gpiod_set_value(gpiod, 1);  /* 逻辑 1 = 激活 */
gpiod_set_value(gpiod, 0);  /* 逻辑 0 = 非激活 */
int val = gpiod_get_value(gpiod);

/* 获取多个 GPIO（按名字区分） */
struct gpio_desc *rst = devm_gpiod_get(&pdev->dev, "reset", GPIOD_OUT_HIGH);
struct gpio_desc *irq_gpio = devm_gpiod_get(&pdev->dev, "irq", GPIOD_IN);
/* 对应设备树: reset-gpios = <...>; irq-gpios = <...>; */
```

**为什么新 API 更好？**

`GPIO_ACTIVE_LOW` 这类极性信息存在设备树里，`gpiod` 自动处理。写 `gpiod_set_value(desc, 1)` 表示「激活」，不管硬件是高电平还是低电平激活。代码的语义更清晰，移植不同硬件时只改设备树，不改驱动代码。

---

## 4.4 按键 GPIO 输入完整示例

```c
struct btn_priv {
    struct gpio_desc *gpiod;
    int irq;
};

static irqreturn_t btn_isr(int irq, void *dev_id)
{
    struct btn_priv *priv = dev_id;
    int val = gpiod_get_value(priv->gpiod);
    printk(KERN_INFO "button: %s\n", val ? "released" : "pressed");
    return IRQ_HANDLED;
}

static int btn_probe(struct platform_device *pdev)
{
    struct btn_priv *priv;
    int ret;

    priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
    if (!priv) return -ENOMEM;

    priv->gpiod = devm_gpiod_get(&pdev->dev, "button", GPIOD_IN);
    if (IS_ERR(priv->gpiod)) return PTR_ERR(priv->gpiod);

    /* 将 GPIO 转为中断号 */
    priv->irq = gpiod_to_irq(priv->gpiod);
    if (priv->irq < 0) return priv->irq;

    /* 注册中断处理函数 */
    ret = devm_request_irq(&pdev->dev, priv->irq, btn_isr,
                           IRQF_TRIGGER_FALLING | IRQF_TRIGGER_RISING,
                           "mybutton", priv);
    if (ret) return ret;

    platform_set_drvdata(pdev, priv);
    dev_info(&pdev->dev, "button driver probed, irq=%d\n", priv->irq);
    return 0;
}
```

---

## 4.5 GPIO sysfs 接口（调试用）

```bash
# 导出 GPIO（如 GPIO1_IO03 = 3）
echo 3 > /sys/class/gpio/export

# 设置方向
echo out > /sys/class/gpio/gpio3/direction

# 控制电平
echo 1 > /sys/class/gpio/gpio3/value
echo 0 > /sys/class/gpio/gpio3/value

# 读取输入
cat /sys/class/gpio/gpio3/value

# 释放
echo 3 > /sys/class/gpio/unexport
```

> 注意：新内核已弃用 sysfs GPIO 接口，推荐使用 `/dev/gpiochipX` + `libgpiod` 用户态库，或在内核驱动里用 gpiod API。

---

## 4.6 面试高频题汇总

**【面试题】pinctrl 和 GPIO 子系统的关系？**

> pinctrl 负责引脚的**复用配置**（这个引脚当 GPIO 用还是当 I2C 用）和**电气属性**（驱动强度、上下拉）。GPIO 子系统负责引脚作为 GPIO 时的**输入/输出控制**。pinctrl 是前提，先把引脚配成 GPIO 功能，GPIO 子系统才能操作它。

**【面试题】`GPIO_ACTIVE_LOW` 的含义？**

> 表示该 GPIO 低电平有效（激活）。使用 gpiod API 时，`gpiod_set_value(desc, 1)` 表示激活，实际输出低电平（0V）。这样驱动代码表达逻辑含义，硬件极性细节留在设备树，代码不需要关心具体硬件接法。

**【面试题】gpio_request 的作用是什么，不调用会怎样？**

> `gpio_request` 在内核里标记该 GPIO 已被某驱动占用，防止多个驱动同时操作同一 GPIO 导致冲突。不调用直接操作 GPIO 在功能上可能正常，但其他驱动可能同时操作同一引脚，且调试时 `/sys/kernel/debug/gpio` 不显示占用信息，难以排查冲突。

**【面试题】如何用命令行测试一个 GPIO？**

> ①导出 GPIO：`echo 引脚号 > /sys/class/gpio/export`；②设置方向：`echo out > /sys/class/gpio/gpioN/direction`；③控制电平：`echo 1 > /sys/class/gpio/gpioN/value`；④或者用新工具：`gpioset gpiochip0 3=1`（需要 libgpiod）。

**【面试题】为什么操作寄存器要用 `writel` 而不是直接赋值？**

> `writel` 包含内存屏障（memory barrier），确保写操作真正发到硬件，不被 CPU 乱序执行或编译器优化掉。直接赋值编译器可能把它优化掉（认为「这个值没有被读，写了也没用」），或 CPU 把多次写合并，导致寄存器没有按预期时序配置。



---


# 第 5 章：中断子系统

## 5.1 为什么需要中断

没有中断时，驱动只能用**轮询**（polling）方式等待硬件事件：

```c
while (!(readl(status_reg) & DATA_READY))
    cpu_relax();  /* 空转等待 */
```

**轮询的问题：**
- CPU 一直忙等，无法做其他事情，浪费算力
- 实时性差：轮询间隔决定响应延迟
- 对低频事件（按键按下）极度低效

**中断的解决方案：**
CPU 继续跑主流程，硬件有事时拉高中断引脚 → CPU 收到信号暂停当前任务 → 跳到中断服务函数（ISR）处理 → 返回被打断的位置继续执行。CPU 不需要等待，效率极高。

---

## 5.2 Linux 中断模型：上半部与下半部

### 为什么要分上半部和下半部

中断服务函数（ISR）运行在**中断上下文**：
- 不能睡眠（`schedule()`、`mutex_lock()` 等会睡眠的操作全部禁止）
- 中断处理期间，同优先级的中断被屏蔽（响应延迟增加）
- 时间必须极短

但很多处理工作（发网络包、写文件、分配内存）耗时较长或需要睡眠。

**解决方案：两阶段处理**

```
硬件中断
    │
    ▼
上半部（Top Half）—— ISR，运行在中断上下文
  • 只做紧急操作：读取硬件状态、清除中断标志
  • 把耗时工作提交给下半部
  • 立即返回（越快越好）
    │
    ▼
下半部（Bottom Half）—— 运行在进程上下文或软中断上下文
  • 可以睡眠（tasklet 不行，workqueue 可以）
  • 做真正的数据处理
```

---

## 5.3 注册中断处理函数

```c
#include <linux/interrupt.h>

/* 原型 */
int request_irq(unsigned int irq,          /* 中断号 */
                irq_handler_t handler,     /* ISR 函数 */
                unsigned long flags,       /* 触发类型 + 共享标志 */
                const char *name,          /* /proc/interrupts 显示名 */
                void *dev_id);             /* 共享中断时区分设备 */

/* 释放 */
void free_irq(unsigned int irq, void *dev_id);

/* devm 版（推荐）：probe 失败或 remove 时自动释放 */
int devm_request_irq(struct device *dev, unsigned int irq,
                     irq_handler_t handler, unsigned long irqflags,
                     const char *devname, void *dev_id);
```

### flags 常用值

| 标志 | 含义 |
| --- | --- |
| `IRQF_TRIGGER_RISING` | 上升沿触发 |
| `IRQF_TRIGGER_FALLING` | 下降沿触发 |
| `IRQF_TRIGGER_HIGH` | 高电平触发 |
| `IRQF_TRIGGER_LOW` | 低电平触发 |
| `IRQF_SHARED` | 多个设备共享同一中断号 |
| `IRQF_ONESHOT` | 中断线程化时保持中断屏蔽直到处理完 |

### ISR 返回值

```c
static irqreturn_t my_isr(int irq, void *dev_id)
{
    struct my_priv *priv = dev_id;

    /* 确认是本设备的中断（共享中断时必须检查） */
    if (!(readl(priv->base + STATUS_REG) & MY_IRQ_BIT))
        return IRQ_NONE;    /* 不是本设备的中断，让其他 ISR 处理 */

    /* 清除中断 */
    writel(MY_IRQ_BIT, priv->base + STATUS_REG);

    /* 提交下半部处理 */
    schedule_work(&priv->work);

    return IRQ_HANDLED;     /* 本设备的中断，已处理 */
}
```

---

## 5.4 下半部机制详解

### softirq（软中断）

软中断在内核编译时静态定义，优先级固定，不可睡眠。网络（NET_RX/TX）、块设备（BLOCK）都用软中断。驱动开发者一般不直接用软中断，了解原理即可。

### tasklet（小任务）

基于软中断实现，动态创建，同一 tasklet 不会在多个 CPU 并行执行，不可睡眠：

```c
struct my_priv {
    struct tasklet_struct tasklet;
    /* ... */
};

/* tasklet 处理函数 */
static void my_tasklet_func(unsigned long data)
{
    struct my_priv *priv = (struct my_priv *)data;
    /* 处理数据，但不能睡眠 */
    dev_info(priv->dev, "tasklet running\n");
}

/* 初始化 */
tasklet_init(&priv->tasklet, my_tasklet_func, (unsigned long)priv);

/* 在 ISR 里调度 */
tasklet_schedule(&priv->tasklet);

/* 清理 */
tasklet_kill(&priv->tasklet);
```

### workqueue（工作队列）

运行在内核线程（kworker）中，**可以睡眠**，是下半部的首选方案：

```c
#include <linux/workqueue.h>

struct my_priv {
    struct work_struct work;
    /* ... */
};

/* 工作函数（可以睡眠） */
static void my_work_func(struct work_struct *work)
{
    struct my_priv *priv = container_of(work, struct my_priv, work);
    /* 可以 mutex_lock、kmalloc、schedule 等 */
    msleep(10);
    dev_info(priv->dev, "work done\n");
}

/* 初始化 */
INIT_WORK(&priv->work, my_work_func);

/* ISR 里调度 */
schedule_work(&priv->work);

/* 等待工作完成（清理时） */
cancel_work_sync(&priv->work);
```

### 延迟工作（delayed_work）

```c
struct delayed_work dwork;
INIT_DELAYED_WORK(&dwork, my_work_func);

/* 100ms 后执行 */
schedule_delayed_work(&dwork, msecs_to_jiffies(100));

/* 取消 */
cancel_delayed_work_sync(&dwork);
```

**【面试题】tasklet 和 workqueue 的区别？**

> | | tasklet | workqueue |
> |---|---|---|
> | 运行上下文 | 软中断上下文 | 内核线程（进程上下文） |
> | 能否睡眠 | **不能** | **能** |
> | 并发 | 同一 tasklet 串行 | 多个 work 可并行 |
> | 使用场景 | 快速、不睡眠的处理 | 需要睡眠或耗时的处理 |
>
> 现代内核推荐优先用 workqueue，tasklet 已在逐步弃用中。

---

## 5.5 中断线程化（threaded IRQ）

中断线程化把上半部（硬中断）和下半部（线程）合并为一个 API，是目前最推荐的写法：

```c
/* 上半部：运行在硬中断上下文，返回 IRQ_WAKE_THREAD 触发线程 */
static irqreturn_t btn_hard_isr(int irq, void *dev_id)
{
    /* 只读硬件寄存器、清中断 */
    return IRQ_WAKE_THREAD;
}

/* 下半部：运行在内核线程，可以睡眠 */
static irqreturn_t btn_thread_fn(int irq, void *dev_id)
{
    struct btn_priv *priv = dev_id;
    int val = gpiod_get_value(priv->gpiod);
    /* 可以 msleep、mutex_lock 等 */
    input_report_key(priv->input, KEY_ENTER, !val);
    input_sync(priv->input);
    return IRQ_HANDLED;
}

/* 注册线程化中断 */
ret = devm_request_threaded_irq(&pdev->dev, irq,
                                btn_hard_isr,  /* 上半部，可传 NULL */
                                btn_thread_fn, /* 下半部线程 */
                                IRQF_TRIGGER_FALLING | IRQF_ONESHOT,
                                "mybutton", priv);
```

**IRQF_ONESHOT 为什么是必须的？**

线程化中断的上半部执行完后，内核会重新使能中断线（允许再次触发）。如果下半部线程还没执行完，新的中断又来了，可能产生竞争。`IRQF_ONESHOT` 让中断线保持屏蔽，直到线程函数执行完，保证了处理的完整性。

---

## 5.6 按键消抖

机械按键按下/释放时，信号会在短时间内抖动（10～20ms 内多次跳变）。处理方式：

```c
struct btn_priv {
    struct gpio_desc *gpiod;
    struct delayed_work dwork;
    struct input_dev *input;
};

static void btn_work(struct work_struct *work)
{
    struct btn_priv *priv = container_of(to_delayed_work(work),
                                         struct btn_priv, dwork);
    int val = gpiod_get_value(priv->gpiod);
    input_report_key(priv->input, KEY_ENTER, !val);
    input_sync(priv->input);
}

static irqreturn_t btn_isr(int irq, void *dev_id)
{
    struct btn_priv *priv = dev_id;
    /* 延迟 20ms 执行，期间如果再次触发则重新计时 */
    mod_delayed_work(system_wq, &priv->dwork, msecs_to_jiffies(20));
    return IRQ_HANDLED;
}
```

---

## 5.7 中断上下文限制总结

```
中断上下文（ISR / tasklet / softirq）里：
  ✅ 可以：readl/writel、spinlock、tasklet_schedule、schedule_work
  ❌ 不能：sleep、mutex_lock、kmalloc(GFP_KERNEL)、printk（大量打印）
              访问用户空间、调用可能阻塞的函数

进程上下文（workqueue / 内核线程）里：
  ✅ 以上都可以
```

**`kmalloc(GFP_KERNEL)` 在中断里为什么不能用？**

`GFP_KERNEL` 允许内核在内存不足时睡眠等待，而中断上下文不能睡眠。应改用 `GFP_ATOMIC`（不睡眠，从紧急内存池分配，可能失败）。

---

## 5.8 面试高频题汇总

**【面试题】什么是中断上下文？有哪些限制？**

> 中断上下文是 CPU 响应硬件中断后，执行 ISR 时所处的运行环境。此时没有对应的进程（`current` 无意义），没有进程地址空间，调度器不能介入。限制：①不能睡眠；②不能持有可睡眠的锁（mutex）；③内存分配必须用 `GFP_ATOMIC`；④不能访问用户空间。

**【面试题】共享中断如何区分是哪个设备触发的？**

> 注册时指定 `IRQF_SHARED`，并传入唯一的 `dev_id`（通常是设备私有数据指针）。中断来临时，内核依次调用所有注册了该中断号的 ISR，每个 ISR 检查自己的硬件状态寄存器判断是否是自己的中断，是则处理并返回 `IRQ_HANDLED`，否则返回 `IRQ_NONE`。

**【面试题】`request_irq` 失败会怎样？**

> `probe` 返回错误码，设备初始化失败，`/dev/` 下没有设备节点。常见失败原因：①中断号无效；②中断号已被占用且未指定 `IRQF_SHARED`；③内存不足。应检查返回值并正确处理错误路径。

**【面试题】`disable_irq` 和 `local_irq_disable` 的区别？**

> `disable_irq(irq)` 禁用特定中断线（通过中断控制器），全局生效，所有 CPU 都不再收到该中断。`local_irq_disable()` 禁用当前 CPU 的所有中断（修改 CPU 状态寄存器），只影响当前 CPU，其他 CPU 不受影响。前者用于保护特定设备的临界区，后者用于极短的原子操作。



---


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



---


# 第 7 章：I²C 子系统

## 7.1 I²C 协议回顾

I²C（Inter-Integrated Circuit）是由 Philips（现 NXP）设计的两线串行总线：

| 信号 | 全称 | 作用 |
| --- | --- | --- |
| SCL | Serial Clock Line | 时钟，由主设备（Master）驱动 |
| SDA | Serial Data Line | 数据，双向，开漏输出 |

**为什么用开漏输出？**

开漏输出只能拉低，不能主动拉高，靠上拉电阻拉高。这样多个设备挂在同一总线上，任何一个设备拉低 SDA/SCL 就能被所有设备感知，实现线与（Wired-AND）逻辑和**总线仲裁**，防止多主设备同时发送时的冲突。

### 时序要点

```
START：SCL 高时，SDA 从高变低
STOP ：SCL 高时，SDA 从低变高
数据 ：SCL 低时改变 SDA，SCL 高时采样 SDA（稳定）
ACK  ：接收方在第 9 个时钟拉低 SDA
NACK ：接收方在第 9 个时钟释放 SDA（保持高）
```

### 访问从设备流程

```
START → 7位地址 + R/W位 → ACK
     → [寄存器地址] → ACK
     → 数据... → ACK → STOP
```

**【面试题】I²C 地址为什么只有 7 位（128 个地址）？**

> 标准 I²C 地址帧是 7 位地址 + 1 位读写标志，共 8 位。7 位最多寻址 128 个设备（0x00～0x7F），其中部分地址保留，实际可用约 112 个。扩展版本（10 位地址）可寻址 1024 个，但需要两次地址帧，兼容性差，较少使用。

---

## 7.2 Linux I²C 子系统架构

```
应用层       open/read/write/ioctl /dev/i2c-0
               │
I²C 核心    i2c_transfer() / i2c_smbus_xxx()
               │
I²C 适配器   i2c_adapter（对应一个 I²C 控制器）
（总线驱动）  probe 时实现 master_xfer()
               │
I²C 设备    i2c_client（对应一个从设备）
（设备驱动）  probe 时操作 i2c_client
```

三个核心结构体：

| 结构体 | 含义 | 谁创建 |
| --- | --- | --- |
| `i2c_adapter` | I²C 控制器（总线） | SoC 厂商提供的总线驱动 |
| `i2c_client` | I²C 从设备实例 | 设备树解析 或 手动注册 |
| `i2c_driver` | I²C 设备驱动 | 驱动开发者编写 |

---

## 7.3 编写 I²C 设备驱动

以 MPU6050 六轴传感器（地址 0x68）为例：

### 设备树配置

```dts
&i2c1 {
    clock-frequency = <400000>;   /* 400kHz Fast Mode */
    status = "okay";

    mpu6050@68 {
        compatible = "invensense,mpu6050";
        reg = <0x68>;             /* I²C 从地址 */
        interrupt-parent = <&gpio1>;
        interrupts = <2 IRQ_TYPE_EDGE_FALLING>;
    };
};
```

### 驱动代码

```c
#include <linux/i2c.h>
#include <linux/module.h>

struct mpu6050_priv {
    struct i2c_client *client;
    /* 传感器数据等 */
};

/* 读单个寄存器 */
static int mpu6050_read_reg(struct i2c_client *client, u8 reg, u8 *val)
{
    int ret;
    /* i2c_smbus_read_byte_data 封装了标准 I²C 寄存器读操作 */
    ret = i2c_smbus_read_byte_data(client, reg);
    if (ret < 0) {
        dev_err(&client->dev, "read reg 0x%02x failed: %d\n", reg, ret);
        return ret;
    }
    *val = (u8)ret;
    return 0;
}

/* 写单个寄存器 */
static int mpu6050_write_reg(struct i2c_client *client, u8 reg, u8 val)
{
    int ret = i2c_smbus_write_byte_data(client, reg, val);
    if (ret < 0)
        dev_err(&client->dev, "write reg 0x%02x failed: %d\n", reg, ret);
    return ret;
}

/* 连续读多个寄存器（如读加速度、陀螺仪数据） */
static int mpu6050_read_regs(struct i2c_client *client,
                              u8 reg, u8 *buf, int len)
{
    struct i2c_msg msgs[2] = {
        {
            /* 第一条消息：写寄存器地址 */
            .addr  = client->addr,
            .flags = 0,           /* 写 */
            .len   = 1,
            .buf   = &reg,
        },
        {
            /* 第二条消息：读数据（Repeated START） */
            .addr  = client->addr,
            .flags = I2C_M_RD,    /* 读 */
            .len   = len,
            .buf   = buf,
        },
    };
    return i2c_transfer(client->adapter, msgs, 2);
}

#define MPU6050_WHO_AM_I    0x75  /* 应读到 0x68 */
#define MPU6050_PWR_MGMT_1  0x6B
#define MPU6050_ACCEL_XOUT_H 0x3B

static int mpu6050_probe(struct i2c_client *client,
                          const struct i2c_device_id *id)
{
    struct mpu6050_priv *priv;
    u8 who_am_i;
    int ret;

    /* 检查设备是否响应 */
    ret = mpu6050_read_reg(client, MPU6050_WHO_AM_I, &who_am_i);
    if (ret < 0) return ret;
    if (who_am_i != 0x68) {
        dev_err(&client->dev, "wrong chip id: 0x%02x\n", who_am_i);
        return -ENODEV;
    }

    priv = devm_kzalloc(&client->dev, sizeof(*priv), GFP_KERNEL);
    if (!priv) return -ENOMEM;
    priv->client = client;
    i2c_set_clientdata(client, priv);

    /* 唤醒器件（清除 SLEEP 位） */
    ret = mpu6050_write_reg(client, MPU6050_PWR_MGMT_1, 0x00);
    if (ret < 0) return ret;

    dev_info(&client->dev, "MPU6050 found, who_am_i=0x%02x\n", who_am_i);
    return 0;
}

static void mpu6050_remove(struct i2c_client *client)
{
    /* devm_ 资源自动释放 */
    dev_info(&client->dev, "MPU6050 removed\n");
}

/* 设备树匹配表 */
static const struct of_device_id mpu6050_of_match[] = {
    { .compatible = "invensense,mpu6050" },
    { }
};
MODULE_DEVICE_TABLE(of, mpu6050_of_match);

/* 非设备树平台兼容 */
static const struct i2c_device_id mpu6050_id[] = {
    { "mpu6050", 0 },
    { }
};
MODULE_DEVICE_TABLE(i2c, mpu6050_id);

static struct i2c_driver mpu6050_driver = {
    .driver = {
        .name           = "mpu6050",
        .of_match_table = mpu6050_of_match,
    },
    .probe    = mpu6050_probe,
    .remove   = mpu6050_remove,
    .id_table = mpu6050_id,
};

module_i2c_driver(mpu6050_driver);  /* 宏替代手写 init/exit */
MODULE_LICENSE("GPL");
```

---

## 7.4 i2c_transfer 和 SMBus 的选择

### SMBus（System Management Bus）

SMBus 是 I²C 的子集协议，有更严格的时序规定，提供了语义更清晰的操作函数：

```c
/* 读单字节寄存器 */
s32 i2c_smbus_read_byte_data(client, reg);

/* 写单字节寄存器 */
s32 i2c_smbus_write_byte_data(client, reg, val);

/* 读 16 位寄存器 */
s32 i2c_smbus_read_word_data(client, reg);

/* 读多字节（最多 32 字节） */
s32 i2c_smbus_read_i2c_block_data(client, reg, len, buf);
```

### i2c_transfer（底层）

```c
/* 自定义消息序列，支持任意长度和方向 */
struct i2c_msg msgs[] = { ... };
ret = i2c_transfer(client->adapter, msgs, ARRAY_SIZE(msgs));
```

**选择原则：** 优先用 SMBus 函数（简单清晰），只有设备不遵循标准寄存器协议时才用 `i2c_transfer`。

---

## 7.5 用户态 I²C 访问（调试）

```bash
# 扫描 i2c-1 总线上的设备
i2cdetect -y 1

# 读 MPU6050（地址0x68）的 WHO_AM_I 寄存器（0x75）
i2cget -y 1 0x68 0x75

# 写寄存器（将 PWR_MGMT_1 写 0）
i2cset -y 1 0x68 0x6B 0x00

# 连续读（读从 0x3B 开始的 6 个字节加速度数据）
i2ctransfer -y 1 w1@0x68 0x3B r6@0x68
```

---

## 7.6 面试高频题汇总

**【面试题】I²C 总线上挂多个设备，驱动如何区分？**

> 每个设备有唯一的 7 位地址，驱动的 `i2c_client.addr` 字段保存该地址。`i2c_transfer` 发送消息时，地址帧里包含目标地址，总线上只有地址匹配的从设备响应。

**【面试题】I²C 的 ACK 和 NACK 分别代表什么？**

> ACK（应答）：接收方在第 9 个时钟把 SDA 拉低，表示成功接收上一字节数据或地址，主设备继续传输。NACK（无应答）：SDA 保持高，表示设备不在线、数据错误、设备忙、或主设备在读操作最后一字节通知从设备停止发送。

**【面试题】`i2c_transfer` 的消息数量和实际 I²C 时序的关系？**

> 每条 `i2c_msg` 对应一段方向一致的传输（写或读），消息间自动插入 Repeated START（不发 STOP）。例如读寄存器操作是两条消息：第一条写寄存器地址，第二条读数据，中间是 Repeated START 而不是 STOP+START，这样寄存器地址和读操作是原子的，不会被其他主设备打断。

**【面试题】`i2c_smbus_read_byte_data` 内部做了什么？**

> 内部调用 `i2c_transfer`，发出两条消息：①写地址帧（设备地址+写）+ 寄存器地址；②Repeated START + 地址帧（设备地址+读）+ 读 1 字节 + 主设备发 NACK（表示读结束）+ STOP。返回读到的字节（成功）或负数错误码。



---


# 第 8 章：SPI 子系统

## 8.1 SPI 协议与 I²C 的对比

SPI（Serial Peripheral Interface）是 Motorola 提出的四线全双工串行总线：

| 信号 | 别名 | 方向 |
| --- | --- | --- |
| SCLK | SCK、CLK | 主 → 从，时钟 |
| MOSI | SDO、DIN | 主 → 从，数据 |
| MISO | SDI、DOUT | 从 → 主，数据 |
| CS/SS | CE、NSS | 主 → 从，片选（低有效） |

**SPI vs I²C：**

| | SPI | I²C |
| --- | --- | --- |
| 线数 | 4（每增加一个设备+1条CS） | 2（无论多少设备） |
| 速度 | 可达数十 MHz～GHz | 标准 100kHz，快速 400kHz |
| 全双工 | **是** | 否 |
| 寻址 | CS 片选（硬件） | 7/10 位软件地址 |
| 典型应用 | SPI Flash、ADC、显示屏 | 传感器、EEPROM、小设备 |

**为什么 SPI 比 I²C 快？**

- SPI 推挽输出，无需上拉电阻，边沿更陡，速度更高
- SPI 全双工，发送和接收同时进行
- SPI 无需应答位（ACK），时序更简单

---

## 8.2 SPI 时钟极性与相位（CPOL/CPHA）

SPI 有 4 种模式，由 CPOL（时钟极性）和 CPHA（时钟相位）决定：

| 模式 | CPOL | CPHA | 空闲时钟 | 采样边沿 |
| --- | --- | --- | --- | --- |
| 0 | 0 | 0 | 低 | 上升沿 |
| 1 | 0 | 1 | 低 | 下降沿 |
| 2 | 1 | 0 | 高 | 下降沿 |
| 3 | 1 | 1 | 高 | 上升沿 |

必须和从设备 datasheet 一致，否则数据错乱。

---

## 8.3 Linux SPI 子系统架构

```
应用层         spidev（用户态 SPI 访问）
               │
SPI 核心       spi_sync() / spi_message / spi_transfer
               │
SPI 控制器    spi_master（对应一个 SPI 控制器）
（总线驱动）
               │
SPI 设备      spi_device（对应一个从设备）
（设备驱动）
```

---

## 8.4 SPI 设备驱动编写

以 W25Q128（SPI NOR Flash）为例：

### 设备树

```dts
&spi1 {
    status = "okay";
    /* SPI 控制器引脚配置 */
    pinctrl-names = "default";
    pinctrl-0 = <&pinctrl_spi1>;

    w25q128: flash@0 {
        compatible = "winbond,w25q128", "jedec,spi-nor";
        reg = <0>;              /* CS0 */
        spi-max-frequency = <50000000>;  /* 50MHz */
        spi-cpha;               /* CPHA=1（可选，根据芯片） */
        /* spi-cpol;            CPOL=1 */
    };
};
```

### 驱动代码

```c
#include <linux/spi/spi.h>
#include <linux/module.h>

struct w25q_priv {
    struct spi_device *spi;
};

/* 发送单条命令（只写） */
static int w25q_cmd(struct spi_device *spi, u8 cmd)
{
    return spi_write(spi, &cmd, 1);
}

/* 读操作（写命令+地址，再读数据） */
static int w25q_read(struct spi_device *spi,
                     u32 addr, u8 *buf, size_t len)
{
    u8 tx[4] = {
        0x03,           /* READ 命令 */
        (addr >> 16) & 0xFF,
        (addr >>  8) & 0xFF,
        addr & 0xFF,
    };

    /* spi_write_then_read：先写后读（不是同时，两次传输） */
    return spi_write_then_read(spi, tx, 4, buf, len);
}

/* 使用 spi_message 的底层方式（全双工或多段传输） */
static int w25q_read_id(struct spi_device *spi, u8 *id_buf)
{
    u8 tx = 0x9F;  /* JEDEC ID 命令 */
    struct spi_transfer xfers[2] = {
        {
            .tx_buf = &tx,
            .len    = 1,
        },
        {
            .rx_buf = id_buf,
            .len    = 3,
        },
    };
    struct spi_message msg;

    spi_message_init(&msg);
    spi_message_add_tail(&xfers[0], &msg);
    spi_message_add_tail(&xfers[1], &msg);

    /* spi_sync：同步传输，阻塞直到完成 */
    return spi_sync(spi, &msg);
}

static int w25q_probe(struct spi_device *spi)
{
    struct w25q_priv *priv;
    u8 id[3];
    int ret;

    /* 配置 SPI 参数（也可在设备树里配置） */
    spi->max_speed_hz = 50000000;
    spi->mode = SPI_MODE_0;
    spi->bits_per_word = 8;
    ret = spi_setup(spi);
    if (ret) return ret;

    priv = devm_kzalloc(&spi->dev, sizeof(*priv), GFP_KERNEL);
    if (!priv) return -ENOMEM;
    priv->spi = spi;
    spi_set_drvdata(spi, priv);

    /* 读取 JEDEC ID */
    ret = w25q_read_id(spi, id);
    if (ret) return ret;

    dev_info(&spi->dev, "W25Q: Manufacturer=0x%02x, Type=0x%02x, Capacity=0x%02x\n",
             id[0], id[1], id[2]);
    return 0;
}

static void w25q_remove(struct spi_device *spi)
{
    dev_info(&spi->dev, "W25Q removed\n");
}

static const struct of_device_id w25q_of_match[] = {
    { .compatible = "winbond,w25q128" },
    { }
};
MODULE_DEVICE_TABLE(of, w25q_of_match);

static const struct spi_device_id w25q_id[] = {
    { "w25q128", 0 },
    { }
};
MODULE_DEVICE_TABLE(spi, w25q_id);

static struct spi_driver w25q_driver = {
    .driver = {
        .name           = "w25q128",
        .of_match_table = w25q_of_match,
    },
    .probe    = w25q_probe,
    .remove   = w25q_remove,
    .id_table = w25q_id,
};

module_spi_driver(w25q_driver);
MODULE_LICENSE("GPL");
```

---

## 8.5 spidev：用户态访问

```c
/* 用户态程序通过 /dev/spidevX.Y 访问 SPI */
int fd = open("/dev/spidev0.0", O_RDWR);

/* 配置 SPI */
uint8_t mode = SPI_MODE_0;
uint32_t speed = 1000000;
ioctl(fd, SPI_IOC_WR_MODE, &mode);
ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed);

/* 全双工传输 */
struct spi_ioc_transfer xfer = {
    .tx_buf = (unsigned long)tx_buf,
    .rx_buf = (unsigned long)rx_buf,
    .len    = len,
};
ioctl(fd, SPI_IOC_MESSAGE(1), &xfer);
```

---

## 8.6 面试高频题汇总

**【面试题】SPI 全双工是什么意思？**

> 全双工指发送和接收同时进行：主设备把数据移出 MOSI，同时从 MISO 移入数据，发送一个字节的同时也收到一个字节（哪怕这个字节是无意义的 0xFF）。I²C 是半双工，同一时刻只能一个方向传输。全双工使 SPI 吞吐量更高，特别适合 DAC/ADC 等需要快速读写的场景。

**【面试题】SPI 通信出现数据错误最常见的原因？**

> ①CPOL/CPHA 模式与从设备不匹配（最常见）；②SPI 时钟频率超过从设备支持的最高速度；③片选信号时序不对（未在 CS 拉低后等待足够时间就开始传输）；④信号线过长导致串扰或反射；⑤MISO 上拉/下拉不当（从设备未驱动时应有确定电平）。

**【面试题】`spi_write_then_read` 和 `spi_sync` 的区别？**

> `spi_write_then_read` 是便利函数，内部封装了两段传输（先写后读，CS 在中间保持有效），等价于两个 `spi_transfer` 的 `spi_message`。`spi_sync` 是底层函数，可以组合任意数量和方向的 `spi_transfer`，灵活性更高，也支持全双工（tx_buf 和 rx_buf 同时有效）。

**【面试题】SPI Flash 的写操作为什么要先发「写使能」命令？**

> SPI Flash（如 W25Q128）有硬件写保护机制，上电默认写保护。写使能命令（WREN, 0x06）设置状态寄存器中的 WEL（Write Enable Latch）位，之后才能执行写或擦除操作。写/擦除完成后 WEL 自动清零，下次写操作还需重新发 WREN。这是防止意外写入的设计。



---


# 第 9 章：输入子系统

## 9.1 为什么需要输入子系统

没有输入子系统时，每种输入设备（按键、触摸屏、鼠标、摇杆）都需要单独的驱动，每个驱动定义自己的 `ioctl` 命令，应用程序需要针对每种设备单独编程，无法通用。

**输入子系统的价值：**
- 统一的事件接口：所有输入设备向用户空间上报同种格式的事件（`struct input_event`）
- 驱动只关注上报事件，不关心如何传给应用
- 应用程序通过 `/dev/input/eventX` 读取事件，代码可复用
- `evdev`、`joydev`、`mousedev` 等处理层把原始事件转换为更高层接口（`/dev/mouse0`、`/dev/js0`）

```
硬件（按键/触摸/鼠标） → 驱动（input_report_xxx）
                                 │
                         输入核心（input core）
                           • 事件过滤、同步
                           • 匹配处理器
                                 │
                    ┌────────────┼────────────┐
                 evdev        mousedev      joydev
              /dev/input/     /dev/mouse0   /dev/js0
               eventX（通用）
```

---

## 9.2 事件类型与编码

每个 `input_event` 包含三个字段：

```c
struct input_event {
    struct timeval time;  /* 时间戳 */
    __u16 type;           /* 事件类型 */
    __u16 code;           /* 事件编码（具体是哪个键/轴） */
    __s32 value;          /* 事件值 */
};
```

常用事件类型（type）：

| 类型 | 值 | 含义 |
| --- | --- | --- |
| `EV_SYN` | 0 | 同步事件（一帧事件结束标志） |
| `EV_KEY` | 1 | 按键/按钮 |
| `EV_REL` | 2 | 相对坐标（鼠标移动） |
| `EV_ABS` | 3 | 绝对坐标（触摸屏） |
| `EV_MSC` | 4 | 杂项 |
| `EV_LED` | 17 | LED |

常用 code 示例：

- `EV_KEY` + `KEY_ENTER`（28）：回车键
- `EV_KEY` + `BTN_LEFT`（0x110）：鼠标左键
- `EV_REL` + `REL_X`（0）：鼠标 X 轴相对移动
- `EV_ABS` + `ABS_X`（0）：触摸屏 X 轴绝对坐标

---

## 9.3 完整按键驱动示例

```c
#include <linux/input.h>
#include <linux/platform_device.h>
#include <linux/gpio/consumer.h>
#include <linux/interrupt.h>

struct btn_priv {
    struct input_dev *input;
    struct gpio_desc *gpiod;
    int irq;
    struct delayed_work dwork;
};

static void btn_work_func(struct work_struct *work)
{
    struct btn_priv *priv = container_of(to_delayed_work(work),
                                         struct btn_priv, dwork);
    int val = gpiod_get_value(priv->gpiod);

    /* 上报按键事件（val=0 表示按下，高电平有效取反） */
    input_report_key(priv->input, KEY_ENTER, !val);
    /* EV_SYN 同步帧：告诉上层这次事件上报完毕 */
    input_sync(priv->input);
}

static irqreturn_t btn_isr(int irq, void *dev_id)
{
    struct btn_priv *priv = dev_id;
    /* 消抖：20ms 后采样 */
    mod_delayed_work(system_wq, &priv->dwork, msecs_to_jiffies(20));
    return IRQ_HANDLED;
}

static int btn_probe(struct platform_device *pdev)
{
    struct btn_priv *priv;
    struct input_dev *input;
    int ret;

    priv = devm_kzalloc(&pdev->dev, sizeof(*priv), GFP_KERNEL);
    if (!priv) return -ENOMEM;

    /* 获取 GPIO */
    priv->gpiod = devm_gpiod_get(&pdev->dev, "button", GPIOD_IN);
    if (IS_ERR(priv->gpiod)) return PTR_ERR(priv->gpiod);

    /* 获取 IRQ */
    priv->irq = gpiod_to_irq(priv->gpiod);
    if (priv->irq < 0) return priv->irq;

    /* 初始化 input_dev */
    input = devm_input_allocate_device(&pdev->dev);
    if (!input) return -ENOMEM;
    priv->input = input;

    input->name    = "mybutton";
    input->dev.parent = &pdev->dev;

    /* 声明该设备支持哪些事件类型和编码 */
    set_bit(EV_KEY, input->evbit);          /* 支持按键事件 */
    set_bit(KEY_ENTER, input->keybit);      /* 支持 ENTER 键 */
    set_bit(EV_SYN, input->evbit);          /* 支持同步事件 */

    /* 注册 input 设备 */
    ret = input_register_device(input);
    if (ret) return ret;

    INIT_DELAYED_WORK(&priv->dwork, btn_work_func);

    /* 注册中断 */
    ret = devm_request_irq(&pdev->dev, priv->irq, btn_isr,
                           IRQF_TRIGGER_FALLING | IRQF_TRIGGER_RISING,
                           "mybutton", priv);
    if (ret) return ret;

    platform_set_drvdata(pdev, priv);
    dev_info(&pdev->dev, "button driver probed\n");
    return 0;
}

static int btn_remove(struct platform_device *pdev)
{
    struct btn_priv *priv = platform_get_drvdata(pdev);
    cancel_delayed_work_sync(&priv->dwork);
    return 0;
}
```

---

## 9.4 触摸屏驱动示例（单点触摸）

```c
struct ts_priv {
    struct input_dev *input;
    /* ... */
};

static void ts_report_event(struct ts_priv *priv, int x, int y, int pressure)
{
    if (pressure) {
        /* 手指按下或移动 */
        input_report_abs(priv->input, ABS_X, x);
        input_report_abs(priv->input, ABS_Y, y);
        input_report_abs(priv->input, ABS_PRESSURE, pressure);
        input_report_key(priv->input, BTN_TOUCH, 1);
    } else {
        /* 手指抬起 */
        input_report_abs(priv->input, ABS_PRESSURE, 0);
        input_report_key(priv->input, BTN_TOUCH, 0);
    }
    input_sync(priv->input);
}

/* probe 里设置 input_dev */
static int ts_probe(struct i2c_client *client, const struct i2c_device_id *id)
{
    struct input_dev *input = devm_input_allocate_device(&client->dev);

    input->name = "my_touchscreen";
    set_bit(EV_ABS, input->evbit);
    set_bit(EV_KEY, input->evbit);
    set_bit(BTN_TOUCH, input->keybit);

    /* 设置坐标范围（必须，否则事件被忽略） */
    input_set_abs_params(input, ABS_X, 0, 4095, 0, 0);
    input_set_abs_params(input, ABS_Y, 0, 4095, 0, 0);
    input_set_abs_params(input, ABS_PRESSURE, 0, 255, 0, 0);

    return input_register_device(input);
}
```

### 多点触摸（MT Protocol B）

```c
/* 需要为每个触摸点分配 slot */
input_set_abs_params(input, ABS_MT_POSITION_X, 0, width, 0, 0);
input_set_abs_params(input, ABS_MT_POSITION_Y, 0, height, 0, 0);
input_mt_init_slots(input, MAX_TOUCH_POINTS, INPUT_MT_DIRECT);

/* 上报事件 */
for (i = 0; i < touch_count; i++) {
    input_mt_slot(input, i);
    input_mt_report_slot_state(input, MT_TOOL_FINGER, true);
    input_report_abs(input, ABS_MT_POSITION_X, points[i].x);
    input_report_abs(input, ABS_MT_POSITION_Y, points[i].y);
}
input_mt_sync_frame(input);
input_sync(input);
```

---

## 9.5 用户态读取事件

```c
#include <linux/input.h>
#include <fcntl.h>

int fd = open("/dev/input/event0", O_RDONLY);
struct input_event ev;

while (read(fd, &ev, sizeof(ev)) == sizeof(ev)) {
    if (ev.type == EV_KEY && ev.code == KEY_ENTER) {
        printf("ENTER %s\n", ev.value ? "pressed" : "released");
    }
}
```

```bash
# 命令行工具查看事件
evtest /dev/input/event0

# 查看所有输入设备
cat /proc/bus/input/devices
```

---

## 9.6 面试高频题汇总

**【面试题】`input_sync` 的作用是什么？**

> 上报 `EV_SYN / SYN_REPORT` 事件，告诉输入核心「这一帧的事件上报完毕」。用户空间的 `read` 调用在收到 `EV_SYN` 后才认为收到了完整的一组事件，进行处理。如果不调用 `input_sync`，事件会在内核缓冲区积累，用户空间一次 `read` 可能得到混乱的事件。

**【面试题】为什么注册 `input_dev` 前必须设置 `evbit` 和 `keybit`？**

> 输入核心通过这些 bit 判断设备支持哪些事件，在 `input_register_device` 时建立事件过滤规则，并向 `evdev` 接口报告设备能力（通过 `ioctl EVIOCGBIT` 暴露给用户空间）。不设置则事件会被丢弃，`evtest` 也看不到事件。

**【面试题】触摸屏为什么要调用 `input_set_abs_params` 设置坐标范围？**

> 输入核心用 min/max 对超出范围的绝对坐标做校验，超出范围的值会被截断或丢弃。用户空间的应用（如 Qt、X11 的 evdev 驱动）也依赖这些参数做坐标归一化（把硬件坐标转换为屏幕坐标）。不设置会导致触摸坐标无效或映射错误。

**【面试题】`/dev/input/event0` 和 `/dev/mouse0` 的区别？**

> `/dev/input/eventX` 是通用事件接口（由 `evdev` 处理器提供），暴露原始的 `input_event` 结构，包含所有类型的事件，是最底层、最完整的接口。`/dev/mouse0` 是由 `mousedev` 处理器提供的，把鼠标事件转换为标准 PS/2 鼠标协议（3字节），只包含鼠标按键和相对移动，不包含键盘等其他事件。现代应用一般直接用 `eventX`，避免协议转换。



---


# 第 10 章：网络设备驱动

## 10.1 网络设备与字符设备的本质区别

网络设备和字符设备的访问方式完全不同：

| | 字符/块设备 | 网络设备 |
| --- | --- | --- |
| 用户访问方式 | `open/read/write /dev/xxx` | 通过 socket，不访问 `/dev/` |
| 内核接口 | VFS `file_operations` | `net_device_ops` |
| 数据单位 | 字节流 / 数据块 | 网络帧（packet）|
| 统计 | 无内置统计 | 内置 rx/tx packets/bytes/errors |
| 调试工具 | `cat`、`dd` | `ifconfig`、`ip`、`tcpdump` |

网络数据包在内核中用 `struct sk_buff`（socket buffer，简称 skb）表示，它是网络子系统的核心数据结构。

---

## 10.2 sk_buff 结构

```
sk_buff 布局（从 head 到 end）：
┌─────────────────────────────────────────────────┐
│  headroom  │    数据区（data～tail）    │ tailroom │
│            │ [ETH头][IP头][TCP头][payload] │         │
└──────────────────────────────────────────────────┘
   ^head      ^data                    ^tail      ^end
```

常用操作：

```c
/* 分配 skb */
struct sk_buff *skb = netdev_alloc_skb(dev, len + NET_IP_ALIGN);
skb_reserve(skb, NET_IP_ALIGN);  /* 保证 IP 头对齐到 4 字节 */

/* 在尾部追加数据（接收时常用） */
u8 *buf = skb_put(skb, len);
memcpy(buf, rx_data, len);

/* 在头部添加协议头（发送时逐层添加） */
skb_push(skb, sizeof(struct ethhdr));

/* 移除头部（接收时逐层剥离） */
skb_pull(skb, sizeof(struct ethhdr));

/* 设置协议 */
skb->protocol = eth_type_trans(skb, dev);

/* 释放 */
dev_kfree_skb(skb);    /* 任意上下文 */
dev_kfree_skb_any(skb); /* 中断/进程上下文均可 */
```

---

## 10.3 网络设备驱动框架

### 最简单的虚拟网络设备

```c
#include <linux/netdevice.h>
#include <linux/etherdevice.h>
#include <linux/skbuff.h>

/* 发送函数：把 skb 发给硬件 */
static netdev_tx_t vnet_xmit(struct sk_buff *skb, struct net_device *dev)
{
    struct vnet_priv *priv = netdev_priv(dev);

    /* 更新统计 */
    dev->stats.tx_packets++;
    dev->stats.tx_bytes += skb->len;

    /* 实际硬件发送（这里是虚拟设备，直接丢弃） */
    dev_kfree_skb(skb);

    return NETDEV_TX_OK;
}

/* 接收函数：把收到的数据封装成 skb 送给内核协议栈 */
static void vnet_rx(struct net_device *dev, u8 *data, int len)
{
    struct sk_buff *skb;

    skb = netdev_alloc_skb(dev, len + NET_IP_ALIGN);
    if (!skb) {
        dev->stats.rx_dropped++;
        return;
    }
    skb_reserve(skb, NET_IP_ALIGN);
    memcpy(skb_put(skb, len), data, len);

    skb->dev = dev;
    skb->protocol = eth_type_trans(skb, dev);   /* 解析以太网帧头，确定上层协议 */
    skb->ip_summed = CHECKSUM_NONE;

    dev->stats.rx_packets++;
    dev->stats.rx_bytes += len;

    /* 送给上层协议栈（NAPI 里用 napi_gro_receive，非 NAPI 用这个） */
    netif_rx(skb);
}

static int vnet_open(struct net_device *dev)
{
    /* 启动发送队列 */
    netif_start_queue(dev);
    return 0;
}

static int vnet_stop(struct net_device *dev)
{
    /* 停止发送队列 */
    netif_stop_queue(dev);
    return 0;
}

static const struct net_device_ops vnet_ops = {
    .ndo_open       = vnet_open,
    .ndo_stop       = vnet_stop,
    .ndo_start_xmit = vnet_xmit,
    .ndo_set_mac_address = eth_mac_addr,
    .ndo_validate_addr   = eth_validate_addr,
};

static int vnet_probe(struct platform_device *pdev)
{
    struct net_device *dev;
    struct vnet_priv *priv;

    /* 分配网络设备（以太网，含私有数据空间） */
    dev = alloc_etherdev(sizeof(struct vnet_priv));
    if (!dev) return -ENOMEM;

    priv = netdev_priv(dev);
    priv->dev = dev;
    SET_NETDEV_DEV(dev, &pdev->dev);

    dev->netdev_ops = &vnet_ops;
    dev->flags |= IFF_NOARP;   /* 虚拟设备：不需要 ARP */

    /* 随机 MAC（实际驱动从硬件读） */
    eth_hw_addr_random(dev);

    platform_set_drvdata(pdev, dev);

    if (register_netdev(dev)) {
        free_netdev(dev);
        return -ENODEV;
    }

    netdev_info(dev, "virtual network device registered\n");
    return 0;
}

static int vnet_remove(struct platform_device *pdev)
{
    struct net_device *dev = platform_get_drvdata(pdev);
    unregister_netdev(dev);
    free_netdev(dev);
    return 0;
}
```

---

## 10.4 NAPI：高性能收包机制

### 为什么需要 NAPI

传统中断收包：每收到一个包产生一个中断，高负载时中断频率可达百万次/秒，中断处理开销超过数据处理本身——这称为**中断风暴**。

**NAPI（New API）的解决思路：**
1. 第一个包到来时，产生中断
2. 中断处理函数屏蔽该中断，调度 NAPI 轮询
3. NAPI 以轮询方式批量处理已到达的包（最多 `budget` 个）
4. 包处理完后，重新开启中断
5. 下一个包到来时再次触发中断……

高负载时变为纯轮询，低负载时仍是中断驱动，兼顾效率和延迟。

```c
struct vnet_priv {
    struct napi_struct napi;
    struct net_device *dev;
    /* ... */
};

/* NAPI 轮询函数 */
static int vnet_poll(struct napi_struct *napi, int budget)
{
    struct vnet_priv *priv = container_of(napi, struct vnet_priv, napi);
    int received = 0;

    while (received < budget && hw_has_packet(priv)) {
        struct sk_buff *skb = vnet_receive_packet(priv);
        if (!skb) break;
        napi_gro_receive(napi, skb);   /* 代替 netif_rx，支持 GRO 合并 */
        received++;
    }

    if (received < budget) {
        /* 包处理完毕，退出轮询模式，重新开启中断 */
        napi_complete_done(napi, received);
        hw_enable_rx_irq(priv);
    }

    return received;
}

/* 中断处理函数 */
static irqreturn_t vnet_isr(int irq, void *dev_id)
{
    struct vnet_priv *priv = dev_id;

    /* 屏蔽 RX 中断，启动 NAPI 轮询 */
    hw_disable_rx_irq(priv);
    napi_schedule(&priv->napi);

    return IRQ_HANDLED;
}

/* probe 里初始化 NAPI */
netif_napi_add(dev, &priv->napi, vnet_poll, 64);  /* budget=64 */
napi_enable(&priv->napi);
```

---

## 10.5 PHY 子系统

以太网控制器（MAC）和物理层芯片（PHY）通过 MDIO 总线通信。Linux 有专门的 PHY 子系统管理 PHY 芯片：

```c
#include <linux/phy.h>

/* 连接 PHY（probe 时调用） */
static int vnet_connect_phy(struct net_device *dev)
{
    struct phy_device *phydev;

    /* 从设备树获取 PHY 节点 */
    phydev = of_phy_connect(dev, of_node,
                            vnet_phy_adjust_link,  /* 连接状态变化回调 */
                            0, PHY_INTERFACE_MODE_RGMII);
    if (!phydev) return -ENODEV;

    phy_start(phydev);   /* 启动自动协商 */
    return 0;
}

/* PHY 链接状态变化时调用 */
static void vnet_phy_adjust_link(struct net_device *dev)
{
    struct phy_device *phydev = dev->phydev;

    if (phydev->link) {
        netdev_info(dev, "link up: %dMbps %s-duplex\n",
                    phydev->speed,
                    phydev->duplex == DUPLEX_FULL ? "full" : "half");
        netif_carrier_on(dev);
    } else {
        netdev_info(dev, "link down\n");
        netif_carrier_off(dev);
    }
}
```

---

## 10.6 调试工具

```bash
# 查看网络接口
ip link show
ifconfig eth0

# 查看统计
ethtool -S eth0
cat /proc/net/dev

# 抓包
tcpdump -i eth0 -n

# 查看驱动信息
ethtool -i eth0

# 测速
iperf3 -s                   # 服务端
iperf3 -c 192.168.1.100     # 客户端

# 查看 PHY 状态
mii-tool eth0
ethtool eth0
```

---

## 10.7 面试高频题汇总

**【面试题】`netif_rx` 和 `napi_gro_receive` 的区别？**

> `netif_rx` 把 skb 放入 CPU 的 input_pkt_queue，触发软中断（NET_RX_SOFTIRQ）处理，每个包都走一次软中断，开销较大。`napi_gro_receive` 在 NAPI 轮询上下文中调用，支持 GRO（Generic Receive Offload）把多个小包合并成大包再送给协议栈，减少协议栈处理次数，提高吞吐量。

**【面试题】`netif_stop_queue` 和 `netif_carrier_off` 的区别？**

> `netif_stop_queue` 停止上层向驱动提交 skb（发送队列满、内存不足时使用），接口仍「在线」，IP 层认为链路正常但队列暂停。`netif_carrier_off` 通知内核物理链路断开（PHY 断线），IP 层认为接口不可达，会触发路由重算，上层 socket 可能收到错误。

**【面试题】sk_buff 的 headroom 为什么要预留？**

> 发送数据时，协议栈从上层到下层逐层添加头部（TCP→IP→Ethernet），每层调用 `skb_push` 在数据前插入头部。如果 headroom 不够，需要重新分配 skb 并拷贝数据，开销很大。预留足够的 headroom（通常是 `NET_SKB_PAD` + 各层头部大小）可以避免这次拷贝。

**【面试题】NAPI 的 budget 参数是什么意思？**

> budget 限制每次轮询最多处理的数据包数量，防止某个设备独占 CPU。Linux 默认 budget 是 300（由 `netdev_budget` 控制），可以通过 `sysctl net.core.netdev_budget` 调整。单个设备的 `napi_poll` 最大处理量由驱动传入的 budget 参数决定（通常 64 或 128）。



---


# 附录

## 附录 A：常用内核调试工具

### A.1 printk 与动态调试

```c
/* 日志级别（数字越小越严重） */
printk(KERN_EMERG   "0: system is unusable\n");
printk(KERN_ALERT   "1: action must be taken immediately\n");
printk(KERN_CRIT    "2: critical conditions\n");
printk(KERN_ERR     "3: error conditions\n");
printk(KERN_WARNING "4: warning conditions\n");
printk(KERN_NOTICE  "5: normal but significant\n");
printk(KERN_INFO    "6: informational\n");
printk(KERN_DEBUG   "7: debug-level messages\n");

/* 推荐使用设备相关的打印宏 */
dev_err(&pdev->dev,  "error: %d\n", ret);
dev_warn(&pdev->dev, "warning message\n");
dev_info(&pdev->dev, "info message\n");
dev_dbg(&pdev->dev,  "debug message\n");  /* 需要 CONFIG_DYNAMIC_DEBUG */

/* 动态调试：运行时开关特定模块的 dev_dbg */
echo "module mydrv +p" > /sys/kernel/debug/dynamic_debug/control
echo "file drivers/mydrv.c +p" > /sys/kernel/debug/dynamic_debug/control
```

### A.2 dmesg

```bash
dmesg -T               # 显示内核日志（带时间戳）
dmesg -T | grep mydrv  # 过滤驱动相关日志
dmesg -C               # 清空日志缓冲区
dmesg -w               # 实时监控（类似 tail -f）
dmesg --level=err,warn # 只显示错误和警告
```

### A.3 /proc 文件系统

```bash
cat /proc/devices          # 已注册的字符/块设备及主设备号
cat /proc/interrupts       # 中断统计（每CPU）
cat /proc/iomem            # 物理内存地址映射
cat /proc/ioports          # I/O 端口映射（x86）
cat /proc/modules          # 已加载的内核模块
cat /proc/bus/input/devices # 输入设备列表
```

### A.4 /sys 文件系统

```bash
ls /sys/bus/platform/devices/    # 平台设备
ls /sys/bus/i2c/devices/         # I²C 设备
ls /sys/class/gpio/              # GPIO
ls /sys/class/input/             # 输入设备
ls /sys/kernel/debug/            # debugfs（需 mount）

# 挂载 debugfs
mount -t debugfs none /sys/kernel/debug

# 查看 GPIO 状态（debugfs）
cat /sys/kernel/debug/gpio

# 查看时钟树
cat /sys/kernel/debug/clk/clk_summary
```

### A.5 KGDB 内核调试

```bash
# 内核编译配置
CONFIG_KGDB=y
CONFIG_KGDB_SERIAL_CONSOLE=y
CONFIG_KGDB_KDB=y

# 启动参数（通过串口 ttyS0 连接调试器）
kgdboc=ttyS0,115200 kgdbwait

# 主机端（使用 gdb）
arm-linux-gnueabihf-gdb vmlinux
(gdb) set remotebaud 115200
(gdb) target remote /dev/ttyUSB0
(gdb) b my_function
(gdb) c
```

---

## 附录 B：驱动开发 Makefile 模板

### B.1 单文件模块

```makefile
# 内核模块名
obj-m += mydriver.o

# 内核源码路径
KDIR ?= /lib/modules/$(shell uname -r)/build

# 交叉编译工具链（本地编译时注释掉）
# CROSS_COMPILE ?= arm-linux-gnueabihf-
# ARCH ?= arm

all:
	$(MAKE) -C $(KDIR) M=$(PWD) ARCH=$(ARCH) CROSS_COMPILE=$(CROSS_COMPILE) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

install:
	$(MAKE) -C $(KDIR) M=$(PWD) modules_install
	depmod -a

.PHONY: all clean install
```

### B.2 多文件模块

```makefile
obj-m += mydriver.o
mydriver-objs := main.o i2c.o gpio.o irq.o

KDIR ?= /lib/modules/$(shell uname -r)/build

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
```

### B.3 树内编译（in-tree）

在 `drivers/misc/` 下添加驱动时：

```makefile
# drivers/misc/Makefile 添加：
obj-$(CONFIG_MY_DRIVER) += mydriver.o
```

```kconfig
# drivers/misc/Kconfig 添加：
config MY_DRIVER
    tristate "My custom driver"
    depends on I2C
    help
      This driver supports my custom device.
      Say M to compile as a loadable module.
```

---

## 附录 C：常用内核 API 速查

### C.1 内存分配

| 函数 | 特点 | 释放 |
| --- | --- | --- |
| `kmalloc(size, GFP_KERNEL)` | 物理连续，小块 | `kfree` |
| `kzalloc(size, GFP_KERNEL)` | 同上，清零 | `kfree` |
| `vmalloc(size)` | 虚拟连续，大块 | `vfree` |
| `devm_kzalloc(dev, size, GFP_KERNEL)` | 绑定设备，自动释放 | 自动 |
| `dma_alloc_coherent(dev, size, &pa, GFP_KERNEL)` | DMA 一致性 | `dma_free_coherent` |
| `get_free_pages(GFP_KERNEL, order)` | 按页分配 | `free_pages` |

### C.2 同步原语

| 原语 | 能否睡眠 | 适用场景 |
| --- | --- | --- |
| `spinlock_t` | 否 | 中断/进程上下文，持有时间极短 |
| `mutex` | 是 | 进程上下文，普通临界区 |
| `semaphore` | 是 | 资源计数（mutex 通常是更好选择） |
| `rwlock_t` | 否 | 读多写少，中断上下文 |
| `rw_semaphore` | 是 | 读多写少，进程上下文 |
| `atomic_t` | — | 简单计数器，无需加锁 |
| `completion` | 是 | 等待某个事件完成 |

### C.3 定时器与延迟

```c
/* 忙等待（不释放 CPU，用于极短延迟） */
udelay(10);          /* 微秒 */
ndelay(100);         /* 纳秒 */

/* 睡眠（释放 CPU，只能在进程上下文） */
msleep(100);         /* 毫秒，精度低 */
usleep_range(1000, 2000);  /* 微秒范围（推荐） */

/* 内核定时器 */
struct timer_list timer;
timer_setup(&timer, my_timer_callback, 0);
mod_timer(&timer, jiffies + msecs_to_jiffies(100));
del_timer_sync(&timer);

/* 高精度定时器 */
struct hrtimer hr;
hrtimer_init(&hr, CLOCK_MONOTONIC, HRTIMER_MODE_REL);
hr.function = my_hrtimer_callback;
hrtimer_start(&hr, ms_to_ktime(100), HRTIMER_MODE_REL);
```

---

## 附录 D：面试题汇总索引

| 面试题 | 所在章节 |
| --- | --- |
| 内核模块与应用程序的区别 | 第 1 章 |
| module_init 宏展开 | 第 1 章 |
| 字符驱动注册流程 | 第 2 章 |
| open 时如何找到 file_operations | 第 2 章 |
| ioctl 命令号设计 | 第 2 章 |
| 为什么要用 copy_from_user | 第 2 章 |
| 设备树解析时机 | 第 3 章 |
| platform_driver probe 调用时机 | 第 3 章 |
| devm_ 系列函数的意义 | 第 3 章 |
| pinctrl 和 GPIO 的关系 | 第 4 章 |
| GPIO_ACTIVE_LOW 含义 | 第 4 章 |
| 中断上下文限制 | 第 5 章 |
| tasklet vs workqueue | 第 5 章 |
| 共享中断如何区分设备 | 第 5 章 |
| IRQF_ONESHOT 作用 | 第 5 章 |
| kmalloc vs vmalloc | 第 6 章 |
| DMA Cache 一致性 | 第 6 章 |
| DMA CPU 地址 vs 总线地址 | 第 6 章 |
| I²C 开漏输出原因 | 第 7 章 |
| I²C 地址 7 位限制 | 第 7 章 |
| i2c_transfer 消息与时序 | 第 7 章 |
| SPI CPOL/CPHA 四种模式 | 第 8 章 |
| SPI Flash 写使能设计 | 第 8 章 |
| input_sync 作用 | 第 9 章 |
| evbit/keybit 为何必须设置 | 第 9 章 |
| NAPI 解决什么问题 | 第 10 章 |
| netif_stop_queue vs carrier_off | 第 10 章 |
| sk_buff headroom 预留原因 | 第 10 章 |

---

## 附录 E：参考资料

### 官方文档
- [Linux Kernel Documentation](https://www.kernel.org/doc/html/latest/)
- [Device Tree Specification](https://www.devicetree.org/specifications/)
- [Linux Driver Model](https://www.kernel.org/doc/html/latest/driver-api/driver-model/index.html)

### 书籍
- 《Linux 设备驱动程序》（第 3 版）—— Jonathan Corbet 等
- 《深入理解 Linux 内核》—— Daniel P. Bovet
- 《嵌入式 Linux 驱动开发指南》—— 韦东山

### 在线资源
- [LWN.net](https://lwn.net/)：Linux 内核最新动态和深度文章
- [elixir.bootlin.com](https://elixir.bootlin.com/)：可交叉引用的内核源码浏览器
- [kernel.org/git](https://git.kernel.org/)：内核 Git 仓库

### 参考板 BSP
- NXP i.MX6ULL EVK（本书主要参考平台）
- Rockchip RK3568（itop-3568 开发板）
- 正点原子 i.MX6U-ALPHA 开发板



---

