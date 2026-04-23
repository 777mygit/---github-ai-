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
