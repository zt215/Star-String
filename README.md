# 星弦-基于yolo动捕和RVC变声系统

Python 客户端 + Java 服务端。

## 技术栈

- Python 客户端：PySide6
- Java 服务端：Spring Boot 4.1.0、Java 17+、Maven
- 数据库：MySQL 8，连接配置在 `server-java/.env`

## 核心能力

- 视频动捕：MediaPipe 人脸 + YOLO11-pose 身体 + MediaPipe Hand 手部关键点，
  可驱动 Live2D / VRM 的头部、眼球、嘴型、手臂、手指
- 手势识别：握拳 / 张开手掌 / 比耶 / 指向 / 点赞 / OK / 摇滚，可映射到动作或表情
- RVC 实时变声：多种 F0 提取、索引检索、门限与降噪
- 语音驱动口型：由输入音频包络驱动嘴型，并估计口型形状（扁口 / 圆唇）
- 输出：UnityCapture 虚拟摄像头（支持透明背景）、虚拟声卡

## 手部驱动的能力边界

手势/手指驱动能不能「一比一还原」，很大程度上取决于**模型给了多少参数**，
这一点很容易被误当成程序 bug：

| 模型命名 | 上臂 | 手腕 | 手指 |
| --- | --- | --- | --- |
| `ParamArmLA/LB`（Cubism 标准，如 hiyori_pro） | 抬落 + 侧摆两个参数 | `ParamHandLB` | `ParamHandL` 一个聚合参数 |
| `syHand1..5{L,R}`（多数中文模型） | 只有 `syHand1` 一个旋转参数 | `syHand3` | `syHand4` 一个聚合参数 |

也就是说：

- **手指**：常见模型每条手臂只有一个「手指」参数，只能整体张开 / 握起，
  做不到逐指还原五指。要逐指还原，模型需要带 `ParamFinger*` 之类的逐指参数
  （程序已支持自动识别），或者改用 VRM 骨骼模型。
- **手臂**：`syHand` 系列没有独立的侧摆参数，程序会把左右侧摆按权重并进
  「上臂旋转」，所以左右移动手掌也能带出动作，但姿态不会和真手完全一致。

指令台画面里每只手旁边会画出五根手指的弯曲度柱状图，
可以直观核对「实际手型」和「识别结果」是否对得上。

## 开发自检

改动动捕 / 变声 / 界面相关代码后，依次跑这几个脚本即可快速回归：

```bash
cd client-python
.venv/Scripts/python.exe ../tools/gesture_selftest.py    # 手势判据
.venv/Scripts/python.exe ../tools/hand_drive_selftest.py # 手指弯曲度 / 手势 / 驱动输出 / 设置合并
.venv/Scripts/python.exe ../tools/lipsync_selftest.py    # 语音口型包络 + Live2D 手部参数绑定与写入
QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe ../tools/ui_smoke_test.py  # 离屏构建主窗口
```

这些脚本都不需要摄像头和麦克风，适合改完代码随手验证。

其中 `hand_drive_selftest.py` 用**合成手型**做回归（按人体指节比例生成 21 个关键点），
覆盖张开 / 握拳 / 比耶三种手型，并验证画面宽高比不影响结果——
手部链路光看摄像头画面是分不出「算法错」还是「模型参数不够」的。
