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
