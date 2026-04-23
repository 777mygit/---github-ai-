# 第 2 章 文件 IO 与标准 IO

## 2.1 为什么存在两套 IO 接口

Linux 里访问文件有两套 API 并存，初学者常感困惑：

| 维度 | 文件 IO（系统调用层） | 标准 IO（C 库层） |
| --- | --- | --- |
| 代表函数 | `open / read / write / close` | `fopen / fread / fwrite / fclose` |
| 头文件 | `<fcntl.h> <unistd.h>` | `<stdio.h>` |
| 返回句柄 | `int fd`（文件描述符） | `FILE *`（文件流指针） |
| 缓冲机制 | 无用户态缓冲，直接进内核 | 用户态缓冲（全缓冲/行缓冲/无缓冲） |
| 可移植性 | POSIX，跨 Unix 系 | C89/C99，连 Windows 也有 |
| 适合场景 | 设备文件、套接字、pipe、需精确控制 | 普通文本/二进制文件、跨平台程序 |

**根本原因**：`open/read/write` 是 Linux 内核暴露出来的系统调用（syscall），一次调用必须切换到内核态，开销约 100~300 ns。对大量小 IO（比如逐字节读文本）来说这个开销累积很大。C 库的标准 IO 在用户态维护一块缓冲区，把很多小读写合并成少量大的系统调用，显著提升吞吐量。

> 口诀：**你需要控制"什么时候进内核"就用文件 IO；你想要"方便地读字符/行/格式"就用标准 IO。**

## 2.2 文件描述符（fd）的本质

每个进程在内核里有一张**文件描述符表**（`files_struct`），fd 就是这张表的下标，表项指向内核的**打开文件表**（`file` 结构体），打开文件表再指向 **inode**（磁盘上文件的元数据）。

```
进程 files_struct           内核 file 结构体          inode（磁盘元数据）
┌──────────────────┐        ┌─────────────────┐      ┌──────────┐
│ fd 0 ──────────► │──────► │ pos / flags     │─────►│ i_mode   │
│ fd 1 ──────────► │        │ f_op            │      │ i_size   │
│ fd 2 ──────────► │        │ f_inode ────────┘      │ i_blocks │
│ fd 3 ──────────► │        └─────────────────┘      └──────────┘
└──────────────────┘
```

要点：

- fd 0/1/2 是进程启动时内核自动分配的：0=stdin，1=stdout，2=stderr
- 同一个文件可以被多个 fd 引用（`dup/dup2`），它们共享同一个 `file` 结构体，因此共享**文件偏移量**
- `fork` 之后子进程复制父进程的文件描述符表，但父子的 fd 仍指向同一个 `file` 结构，因此共享偏移量——这是很多并发 bug 的根源
- fd 是进程级别的，不同进程的 fd 数字相同没有任何关系

## 2.3 open / openat

### 函数原型

```c
#include <fcntl.h>
int open(const char *path, int flags);
int open(const char *path, int flags, mode_t mode);  /* 创建时才需要 mode */
int openat(int dirfd, const char *path, int flags, ...);
```

成功返回非负 fd，失败返回 -1 并设置 `errno`。

### flags 标志

| 标志 | 含义 |
| --- | --- |
| `O_RDONLY` | 只读（值为 0） |
| `O_WRONLY` | 只写 |
| `O_RDWR` | 读写 |
| `O_CREAT` | 不存在则创建，需指定 mode |
| `O_EXCL` | 与 `O_CREAT` 合用，若文件已存在则报错 `EEXIST` |
| `O_TRUNC` | 打开已存在文件时截断为 0 |
| `O_APPEND` | 每次写之前原子地移到文件末尾 |
| `O_NONBLOCK` | 非阻塞模式（主要对设备/管道/socket 有意义） |
| `O_SYNC` / `O_DSYNC` | 写入后等待数据落盘（`O_DSYNC` 只等数据，不等元数据） |
| `O_CLOEXEC` | `exec` 后自动关闭，避免 fd 泄漏到子进程 |
| `O_DIRECTORY` | 要求 path 必须是目录，否则报错 |
| `O_TMPFILE` | 创建匿名临时文件（Linux 3.11+） |

### 为什么要有 openat

`openat` 是 Linux 2.6.16 加入的 POSIX.1-2008 接口，解决**TOCTTOU（检查时到使用时）竞态**和**相对路径的线程安全问题**：

- 多线程里调用 `chdir` 再 `open` 相对路径是危险的（`chdir` 改的是进程级 cwd，所有线程共享）
- `openat(dirfd, "subdir/file", ...)` 让相对路径的基准目录是 `dirfd`，每个线程可以持有自己的目录 fd

```c
int dirfd = open("/var/log", O_RDONLY | O_DIRECTORY);
int fd    = openat(dirfd, "app.log", O_WRONLY | O_APPEND | O_CREAT, 0644);
```

### 内核调用链

```
用户态 open()
  └─ syscall(SYS_openat, AT_FDCWD, path, flags, mode)   // 现代内核 open 已合并到 openat
       └─ do_sys_openat2()
            ├─ getname()                  // 从用户态复制路径字符串
            ├─ get_unused_fd_flags()      // 在 files_struct 里找一个空槽位
            ├─ do_filp_open()
            │    ├─ path_openat()         // 路径解析（逐层查 dentry 缓存）
            │    │    ├─ link_path_walk() // 逐层解析目录分量
            │    │    └─ do_open()        // 调用文件系统的 .open() 方法
            │    └─ 返回 struct file *
            └─ fd_install()               // 把 file* 装入 fd 槽
```

### 示例：带错误处理的 open

```c
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>

int main(void)
{
    /* O_CLOEXEC 是好习惯，防止 fd 泄漏给 exec 出的子进程 */
    int fd = open("/tmp/test.txt",
                  O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0) {
        fprintf(stderr, "open: %s\n", strerror(errno));
        return EXIT_FAILURE;
    }

    const char *msg = "hello, linux io\n";
    ssize_t n = write(fd, msg, strlen(msg));
    if (n < 0) {
        fprintf(stderr, "write: %s\n", strerror(errno));
    }

    close(fd);
    return EXIT_SUCCESS;
}
```

## 2.4 read / write / lseek

### 函数原型

```c
#include <unistd.h>
ssize_t read (int fd, void *buf, size_t count);
ssize_t write(int fd, const void *buf, size_t count);
off_t   lseek(int fd, off_t offset, int whence);
```

### 为什么 read 返回的字节数可能少于 count

这是最常见的坑。下面几种情况都会导致"短读"：

- **普通文件**：读到文件末尾剩余字节不足 count
- **管道 / socket**：对端写入不足 count 字节就返回了
- **终端（tty）**：行缓冲，用户按下回车才交付数据
- **信号打断**：收到信号，read 返回 -1 且 `errno == EINTR`
- **大文件**：内核 page cache 还没准备好，部分数据先返回

因此**正确的读循环**必须像这样：

```c
ssize_t read_full(int fd, void *buf, size_t len)
{
    size_t done = 0;
    while (done < len) {
        ssize_t n = read(fd, (char *)buf + done, len - done);
        if (n == 0) break;          /* EOF */
        if (n < 0) {
            if (errno == EINTR) continue;   /* 信号打断，重试 */
            return -1;              /* 真正的错误 */
        }
        done += (size_t)n;
    }
    return (ssize_t)done;
}
```

write 同理，虽然普通文件的 write 一般不会短写，但 socket / pipe 一定要做完整写循环。

### lseek 的 whence

| whence | 含义 |
| --- | --- |
| `SEEK_SET` | 从文件头偏移 offset 字节 |
| `SEEK_CUR` | 从当前位置偏移 offset 字节（offset 可为负） |
| `SEEK_END` | 从文件末尾偏移 offset 字节（常用 `lseek(fd,0,SEEK_END)` 获取大小） |
| `SEEK_HOLE` | 定位到下一个"空洞"起点（稀疏文件，Linux 3.1+） |
| `SEEK_DATA` | 定位到下一段有实际数据的区域（稀疏文件） |

### 内核调用链（read）

```
用户态 read(fd, buf, n)
  └─ syscall(SYS_read, fd, buf, n)
       └─ ksys_read()
            ├─ fdget_pos(fd)          // 从当前进程的 files_struct 里取出 file*，持有引用
            ├─ vfs_read()
            │    ├─ file->f_op->read_iter()   // 调用具体文件系统（ext4/tmpfs/...）
            │    │    ├─ generic_file_read_iter()  // Page Cache 路径（普通文件）
            │    │    │    ├─ find_get_pages()     // 从 Page Cache 找页
            │    │    │    └─ copy_page_to_iter()  // 把页内容复制到用户 buf
            │    │    └─ 设备驱动的 read（字符设备）
            │    └─ 更新 file->f_pos
            └─ fdput_pos()           // 释放引用
```

**Page Cache** 是理解 Linux IO 性能的关键：内核在内存里为磁盘数据维护一个缓存，第一次 read 从磁盘载入 page cache，之后的 read 直接从内存返回，极快。`write` 也先写 page cache，由内核的 writeback 机制异步刷盘。这也是为什么进程崩溃不会丢数据，但突然断电会——page cache 里的"脏页"还没写到磁盘。

## 2.5 文件描述符的复制：dup / dup2 / dup3

```c
#include <unistd.h>
int dup (int oldfd);
int dup2(int oldfd, int newfd);
int dup3(int oldfd, int newfd, int flags);  /* flags 目前只有 O_CLOEXEC */
```

`dup` 返回最小可用 fd 号；`dup2` 把 oldfd 复制到指定的 newfd（如果 newfd 已打开则先关闭）。两个 fd 共享同一个 `file` 结构，因此共享**偏移量**和**状态标志**，但各自有独立的 `O_CLOEXEC` 标志（file descriptor flags）。

### 重定向的实现原理

Shell 实现 `cmd > file.txt` 就是这样做的：

```c
/* 子进程里 */
int fd = open("file.txt", O_WRONLY | O_CREAT | O_TRUNC, 0644);
dup2(fd, STDOUT_FILENO);  // 把 fd 复制到 1 号槽
close(fd);                // 关掉多余的 fd
execvp("cmd", argv);      // 执行命令，此时 stdout 已经是 file.txt
```

### 管道重定向示例

```c
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    int pipefd[2];
    if (pipe(pipefd) < 0) { perror("pipe"); exit(1); }

    pid_t pid = fork();
    if (pid == 0) {
        /* 子进程：把 stdout 重定向到管道写端 */
        close(pipefd[0]);
        dup2(pipefd[1], STDOUT_FILENO);
        close(pipefd[1]);
        execlp("ls", "ls", "-l", NULL);
        perror("exec"); exit(1);
    }
    /* 父进程：从管道读 */
    close(pipefd[1]);
    char buf[256];
    ssize_t n;
    while ((n = read(pipefd[0], buf, sizeof(buf))) > 0)
        write(STDOUT_FILENO, buf, (size_t)n);
    close(pipefd[0]);
    return 0;
}
```

## 2.6 fcntl —— 运行时控制文件描述符

```c
#include <fcntl.h>
int fcntl(int fd, int cmd, ...);
```

`fcntl` 是"对已打开 fd 的万能控制"，常用 cmd：

| cmd | 作用 |
| --- | --- |
| `F_DUPFD` | 复制 fd（类似 dup，但返回 >= arg 的最小可用 fd） |
| `F_DUPFD_CLOEXEC` | 同上，新 fd 带 `O_CLOEXEC` |
| `F_GETFL` / `F_SETFL` | 获取/修改文件状态标志（`O_NONBLOCK`、`O_APPEND` 等） |
| `F_GETFD` / `F_SETFD` | 获取/修改文件描述符标志（目前只有 `FD_CLOEXEC`） |
| `F_GETLK` / `F_SETLK` / `F_SETLKW` | POSIX 记录锁（建议锁，非强制） |
| `F_GET_SEALS` / `F_ADD_SEALS` | 内存文件密封（`memfd_create`） |

### 运行时追加 O_NONBLOCK（非常常用）

```c
int flags = fcntl(fd, F_GETFL);
if (flags < 0) { perror("F_GETFL"); }
flags |= O_NONBLOCK;
if (fcntl(fd, F_SETFL, flags) < 0) { perror("F_SETFL"); }
```

> 注意：**永远不要用 `fcntl(fd, F_SETFL, O_NONBLOCK)`**，这会把其他标志（如 `O_APPEND`）全部清掉。

## 2.7 标准 IO（stdio）

### FILE* 与缓冲

`FILE` 是 C 库在用户态维护的结构，包含：

- 底层 fd（通过 `fileno(fp)` 可取到）
- 读/写缓冲区（通常 8 KB）
- 缓冲区当前指针、剩余字节数
- 错误标志 / EOF 标志

**三种缓冲模式**：

| 模式 | 何时刷入内核 | 适合场景 |
| --- | --- | --- |
| 全缓冲（_IOFBF） | 缓冲区满或 `fflush` | 普通磁盘文件（默认） |
| 行缓冲（_IOLBF） | 遇到 `\n` 或缓冲区满或 `fflush` | stdout 连终端时（默认） |
| 无缓冲（_IONBF） | 立即 | stderr（默认）、实时日志 |

手动设置：

```c
/* 必须在第一次 IO 之前调用 */
setvbuf(fp, NULL, _IOLBF, 0);   /* 行缓冲，内核自动分配缓冲 */
setvbuf(fp, buf, _IOFBF, 4096); /* 全缓冲，用自己的 buf */
```

### 为什么 printf 有时不能立刻在屏幕上看到

`printf` 写的是 stdout，stdout 连着终端时是行缓冲，没有 `\n` 就不会刷出来。在嵌入式里常见的坑：

```c
printf("loading...");   // 不换行，看不到
sleep(3);
printf("done\n");       // 这时才一起显示
```

解决：加 `fflush(stdout)` 或打印 `\n` 或改成无缓冲。

### fopen / fclose

```c
#include <stdio.h>
FILE *fopen(const char *path, const char *mode);
int   fclose(FILE *fp);
```

| mode | 含义 |
| --- | --- |
| `"r"` | 只读，文件不存在返回 NULL |
| `"w"` | 只写，截断或创建 |
| `"a"` | 追加写，创建或末尾追加 |
| `"r+"` | 读写，文件必须存在 |
| `"w+"` | 读写，截断或创建 |
| `"a+"` | 读追加写，可从任意位置读 |
| `"b"` 后缀 | 二进制模式（Linux 无区别，Windows 有区别） |
| `"e"` 后缀 | `O_CLOEXEC`（glibc 2.7+ 扩展） |

`fclose` 会先 `fflush` 缓冲区再关闭底层 fd。如果 `fflush` 失败（比如磁盘满），`fclose` 返回 `EOF`，但 fd 仍然已关闭——这是个坑，磁盘写错误很容易被忽视。

### fread / fwrite

```c
size_t fread (void *ptr, size_t size, size_t nmemb, FILE *fp);
size_t fwrite(const void *ptr, size_t size, size_t nmemb, FILE *fp);
```

返回成功读/写的**元素个数**（不是字节数）。当返回值 < nmemb 时，用 `feof(fp)` 判断是 EOF，用 `ferror(fp)` 判断是错误。

### 字符/行级 IO

```c
int  fgetc(FILE *fp);               /* 读一个字符，返回 int（EOF = -1） */
int  fputc(int c, FILE *fp);
char *fgets(char *buf, int n, FILE *fp);  /* 读一行，保留 \n，末尾加 \0 */
int  fputs(const char *s, FILE *fp);      /* 不加 \n */
int  getline(char **buf, size_t *n, FILE *fp); /* 自动分配，可读任意长行 */
```

> 不要用 `gets`（已从 C11 删除）。用 `fgets` 或 `getline`。

### 格式化 IO

```c
int fprintf(FILE *fp, const char *fmt, ...);
int fscanf (FILE *fp, const char *fmt, ...);
int snprintf(char *buf, size_t n, const char *fmt, ...); /* 不会溢出，推荐 */
```

### 定位

```c
int  fseek (FILE *fp, long offset, int whence);  /* 同 lseek 的 whence */
long ftell (FILE *fp);
int  fseeko(FILE *fp, off_t offset, int whence); /* 大文件，off_t 可能是 64 位 */
off_t ftello(FILE *fp);
void rewind(FILE *fp);     /* 等价于 fseek(fp, 0, SEEK_SET) + 清错误标志 */
```

### 标准 IO 调用链

```
fprintf(fp, "hello")
  └─ __vfprintf_internal()         // 格式化到 fp->_IO_buf
       └─ _IO_write_base 判断缓冲区是否满
            └─ _IO_do_write()       // 调用 _IO_SYSWRITE
                 └─ write(fp->_fileno, buf, n)  // 系统调用
                      └─ （同文件 IO write 的内核路径）
```

## 2.8 O_SYNC / fsync / fdatasync —— 数据持久化

Page Cache 提高了性能，但带来了持久化问题。三个级别：

| 方法 | 范围 | 说明 |
| --- | --- | --- |
| `write()` | 写入 page cache | 进程崩溃安全，掉电不保证 |
| `fsync(fd)` | 数据 + 元数据落盘 | 保证掉电安全，速度最慢 |
| `fdatasync(fd)` | 只保证数据落盘（文件大小变化时元数据也同步） | 比 fsync 稍快，适合日志 |
| `O_SYNC` 打开标志 | 每次 write 都等数据+元数据落盘 | 性能最差，一般不用 |
| `O_DSYNC` 打开标志 | 每次 write 等数据落盘 | 适合数据库 WAL 文件 |
| `sync()` | 全系统脏页 | 无法判断是否成功，不推荐 |

**为什么 `fsync` 还不够？**  
在有写缓存的存储（SATA HDD / 部分 SSD 控制器）上，`fsync` 只能保证数据进入磁盘控制器的缓存，断电时控制器缓存也可能丢失。需要在磁盘层面开 `write cache = disabled` 或磁盘带电池备份（BBU）才能真正保证。

```c
/* 正确的持久化写：写完 fsync 文件，再 fsync 目录（保证目录项更新落盘） */
int fd = open("data.bin", O_WRONLY | O_CREAT | O_TRUNC, 0644);
write(fd, buf, len);
fsync(fd);   /* 先刷文件 */
close(fd);

int dir = open(".", O_RDONLY);
fsync(dir);  /* 再刷目录——这步常被忘 */
close(dir);
```

## 2.9 散布/聚集 IO：readv / writev

```c
#include <sys/uio.h>
struct iovec { void *iov_base; size_t iov_len; };
ssize_t readv (int fd, const struct iovec *iov, int iovcnt);
ssize_t writev(int fd, const struct iovec *iov, int iovcnt);
```

**为什么用 writev 而不是多次 write？**

1. **原子性**：对管道和 socket，writev 保证所有向量里的数据连续写出，不会被其他进程的写插入；多次 write 做不到
2. **减少系统调用次数**：一次 syscall 代替 N 次，降低上下文切换开销
3. **避免内存拷贝**：不需要把多个缓冲区先合并到一个大缓冲再写

常见场景：HTTP 响应头和响应体分别在两块内存里，一次 writev 一起发出。

```c
struct iovec iov[2];
char header[] = "HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\n";
char body[]   = "hello";
iov[0].iov_base = header; iov[0].iov_len = strlen(header);
iov[1].iov_base = body;   iov[1].iov_len = strlen(body);
writev(sockfd, iov, 2);
```

## 2.10 内存映射 IO：mmap

```c
#include <sys/mman.h>
void *mmap(void *addr, size_t length, int prot, int flags, int fd, off_t offset);
int   munmap(void *addr, size_t length);
int   msync(void *addr, size_t length, int flags);
```

### mmap 的原理

`mmap` 把文件的一个区间**映射到进程的虚拟地址空间**。访问那块内存就是在访问文件，完全省掉了 `read/write` 的用户态-内核态切换和数据拷贝。

```
虚拟地址 [0x7f000000, 0x7f001000)  ──映射──►  磁盘文件 file.bin 的第 0 页
   │
   │  （第一次访问，触发缺页中断）
   ▼
内核从磁盘加载这一页到 page cache，再把 page cache 的物理页直接挂到进程页表
```

从此读写那段虚拟地址，就是在读写 page cache，内核 writeback 机制会把脏页刷回磁盘。

### prot 和 flags

| 参数 | 常用值 |
| --- | --- |
| prot | `PROT_READ`、`PROT_WRITE`、`PROT_EXEC`（可组合） |
| flags | `MAP_SHARED`（修改写回文件）、`MAP_PRIVATE`（写时拷贝，不改文件）、`MAP_ANONYMOUS`（匿名映射，fd=-1，常用于大块内存分配）、`MAP_FIXED` |

### 什么时候用 mmap

- **大文件随机读写**：避免 lseek + read 的多次 syscall，直接按下标访问
- **进程间共享内存**：`MAP_SHARED` + 同一文件，父子或无亲缘进程共享
- **执行文件/动态库加载**：内核本身就是用 mmap 把 ELF 段映射进来的
- **不适合**：小文件、只顺序读一次（`read` + page cache 性能差不多，但 mmap 有建立页表的开销）

```c
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <string.h>

int main(void)
{
    int fd = open("/tmp/mmap_test.txt", O_RDWR | O_CREAT | O_TRUNC, 0644);
    /* 文件必须有足够大小，否则 SIGBUS */
    ftruncate(fd, 4096);

    char *p = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);  /* mmap 之后 fd 可以关掉，映射仍然有效 */

    memcpy(p, "hello mmap\n", 11);
    msync(p, 4096, MS_SYNC);   /* 确保写回磁盘 */
    munmap(p, 4096);
    return 0;
}
```

## 2.11 文件加锁

### 强制锁 vs 建议锁

Linux 的文件锁默认是**建议锁**（advisory lock）：不加锁的进程仍然可以读写文件，加锁只对"也在用锁"的进程有效。真正意义上的强制锁需要挂载时加 `mand` 选项，几乎不用。

### flock（BSD 风格，整文件锁）

```c
#include <sys/file.h>
int flock(int fd, int operation);
/* operation: LOCK_SH（共享/读锁）LOCK_EX（独占/写锁）LOCK_UN（解锁）LOCK_NB（非阻塞） */
```

`flock` 锁定的是整个文件，而且锁关联的是 `open file description`，不是 fd——所以 `dup` 出的 fd 和原 fd 共享锁，`fork` 出的子进程也共享。

### fcntl POSIX 记录锁（字节范围锁）

```c
struct flock fl = {
    .l_type   = F_WRLCK,      /* F_RDLCK / F_WRLCK / F_UNLCK */
    .l_whence = SEEK_SET,
    .l_start  = 0,
    .l_len    = 0,            /* 0 = 到文件末尾 */
};
fcntl(fd, F_SETLKW, &fl);    /* W = 阻塞等待 */
/* ... 临界区 ... */
fl.l_type = F_UNLCK;
fcntl(fd, F_SETLK, &fl);
```

POSIX 锁关联的是**进程 + inode**，同一进程的任意 fd 都能解掉同一文件的锁，且进程退出时锁自动释放——这使得 POSIX 锁在多线程里很危险（线程 A 加的锁，线程 B 可以解锁）。

| 特性 | flock | fcntl POSIX 锁 |
| --- | --- | --- |
| 锁粒度 | 整文件 | 字节范围 |
| 锁关联对象 | open file description | 进程 + inode |
| 进程退出自动释放 | 是 | 是 |
| fork 后子进程继承 | 共享 | 不继承（子进程有独立锁状态） |
| NFS 支持 | 否 | 是（NFSv4+） |
| 线程安全 | 相对安全 | 不安全 |

## 2.12 综合示例：带缓冲的日志写入器

结合 `O_APPEND`（原子追加）+ `O_CLOEXEC` + 按大小轮转 + `fsync`：

```c
#define _GNU_SOURCE
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <sys/stat.h>

#define LOG_PATH "/tmp/app.log"
#define MAX_SIZE (1 * 1024 * 1024)  /* 1 MB 触发轮转 */

static int g_fd = -1;

static void log_open(void)
{
    g_fd = open(LOG_PATH, O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0644);
    if (g_fd < 0) { perror("log_open"); exit(1); }
}

static void log_rotate(void)
{
    /* 简单轮转：重命名旧文件，重新创建 */
    char old[256];
    snprintf(old, sizeof(old), "%s.1", LOG_PATH);
    close(g_fd);
    rename(LOG_PATH, old);
    log_open();
}

void log_write(const char *msg)
{
    if (g_fd < 0) log_open();

    /* 检查文件大小 */
    struct stat st;
    if (fstat(g_fd, &st) == 0 && st.st_size >= MAX_SIZE)
        log_rotate();

    time_t t = time(NULL);
    char buf[512];
    int  n = snprintf(buf, sizeof(buf), "[%ld] %s\n", (long)t, msg);

    /* O_APPEND 保证多进程并发追加是原子的（对 < PIPE_BUF 的写） */
    write(g_fd, buf, (size_t)n);
}

int main(void)
{
    for (int i = 0; i < 5; i++) {
        char msg[64];
        snprintf(msg, sizeof(msg), "message #%d", i);
        log_write(msg);
    }
    fsync(g_fd);
    close(g_fd);
    return 0;
}
```

## 2.13 性能对比与选型建议

| 场景 | 推荐接口 | 原因 |
| --- | --- | --- |
| 顺序读大文件（> 64 KB 块） | `read` + `posix_fadvise(SEQUENTIAL)` | 直接读，告知内核预读 |
| 随机读大文件（多次小块） | `mmap` | 避免重复 syscall，利用页表 |
| 写追加日志（多进程安全） | `O_APPEND` + `write` | `O_APPEND` 移位+写 是原子的 |
| 文本解析、行读取 | `getline / fgets` | stdio 缓冲减少 syscall |
| 网络数据合并发送 | `writev` | 原子 + 少 syscall |
| 大量 printf 输出 | `setvbuf(_IOFBF)` + 结尾 `fflush` | 减少 write 次数 |
| 需要掉电保证 | `fdatasync` 或 `O_DSYNC` | 按需选，性能开销差很多 |

## 2.14 易错点汇总

- **忘记检查 open 返回值**：fd < 0 时继续 read/write 会对 fd=-1 操作，报 `EBADF`，而且行为未定义
- **fd 泄漏**：所有出口（包括 return / goto）都要 close(fd)；嵌入式里 fd 上限默认 1024，泄漏几百个就崩
- **短读没处理**：`read` 返回比期望少，直接用就会出数据错位
- **fclose 没检查返回值**：磁盘满时 fclose 失败，数据丢失且无提示
- **混用 fd 和 FILE***：`read(fileno(fp), ...)` 和 `fread` 混用时缓冲区不同步，会漏数据
- **O_APPEND 不等于线程安全**：`O_APPEND` 保护的是 lseek+write 的原子性，但 `write` 本身在多线程里可能被拆分（超过 PIPE_BUF 时）
- **mmap 后关了文件再 ftruncate**：改 mmap 范围之外的文件大小，映射区域会出现 SIGBUS
- **lseek 对管道/socket 无效**：lseek 返回 -1，errno = ESPIPE
