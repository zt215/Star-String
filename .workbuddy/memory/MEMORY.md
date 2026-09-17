# 星弦 · 项目长期备忘

**详细笔记见同目录 `星弦-动捕驱动手册.md`**（驱动链路/手势/手臂 IK/去抖/尺度来源/
VRM/Live2D 边界/定位套路/自定义姿势手势）。改 `motion_capture`、`rig` 或各 View 的
驱动链前先读它。本文件只留红线。

## 项目约定

- 客户端 `client-python/`（PySide6）。主界面 `home_window.py` 是单文件巨类，改动前
  先读盘确认最新内容（本机曾出现工作副本被外部编辑器改写）。
- 配置**不在项目目录**：离线档 `~/.star_string/local_profile/settings.json`，账号档
  `~/.star_string/accounts_data/<account>/settings.json`。`settings_store.py` 分段读写，
  新增字段必须同时加进对应 `DEFAULT_*`。`_merge_motion()` 逐层合并
  `params`/`gesture_actions`/`gesture_profiles`，**不要**退回 `dict(DEFAULT, **user)`
  浅合并（老配置会整块顶掉新参数）。
- 新增驱动键同步改七处：`_extract_drive` 默认字典、`_apply_drive_params` 倍率表、
  `_swap_lr`、`DEFAULT_MOTION_SETTINGS["params"]`、`vrm_view._detect_params`、
  驱动数值卡片、`rig._default_drive`。手部 24 键必须备齐归零，否则手离开画面时手指
  卡在上一帧姿势。

## 红线（改过就别退回去）

- **纯几何量的坐标源优先级：世界坐标 > 像素 > 归一化**。归一化按画面宽高缩放 x/y，
  夹角与长度比整体失真（只用来定手腕在画面里的左右上下）；像素在手正对镜头时会把
  卷起的手指压平；世界坐标（米制三维）与朝向无关，几何量优先用它。唯一例外是
  **手腕 roll**（「手腕在画面里倾斜多少」是屏幕空间的量）。手指弯曲度用了哪个源
  必须能查（`current_hand_geometry`，退化成像素时读数会失真）。
- 手势识别必须同时吃 `hand_world_landmarks`；拇指「张开」判据是「拇指尖到食指近端
  指骨的距离 ÷ 手掌尺度」，**不是**拇指自己的指节夹角。
- **分类器的绝对阈值有死区**（指节状态 0.35~0.6 两头不靠）：四指全落进去就
  `count==0 → 握拳`（真实的手做单指恰好落这儿）。`count==0` 前必须过一遍相对判据
  「最直的一根领先第二名多少」（`_SOLO_GAP`/`_SOLO_MIN`）。
- **姿势距离带「单根手指峰值」项**（`_PEAK_FINGER_WEIGHT=0.6`）：加权 RMS 会摊薄
  稀疏的手型（旧实现「单指 vs 握拳」只有 0.153 < 默认容差 0.16 → 互相触发）。标准档
  换算成单指误差 ≈ 0.27。**改了度量，已录的姿势模板要删掉重录**（旧值是被投影压平的）。
- 状态行必须**按链路分清楚**（「手部驱动」卡片那行 = `_hands_status_line()`）：自定义
  姿势命中 → `手势：<名字>`，内置触发 → `手势：<手型>`，都没触发才写 `手型：握拳`。
  只报手型原始文字会让人以为「系统把我的手势认成握拳」（执行其实是对的）。报手型用
  `current_hand_shapes()`（每帧覆盖），**不能**用 `_gesture_active`（去抖后保留旧值）。
  见手册 10.6~10.9。
- 手势动作菜单**按模型能力动态生成**（`model_actions.py`，纯函数可无 GPU 单测），别
  写死列表；模型未加载时绝不改写映射。
- **手势配置按模型各存一份**（`gesture_profiles`，键 `类型:名字`）。默认与自定义手势
  同在一个列表，「删除默认手势」= 移除该 id；默认手势动作另镜像进老字段
  `gesture_actions`（仅作模型未加载时的兜底），落盘必须**整份替换**，否则删掉的仍会
  触发。`rows_for` 对「存过但空列表」返回空（用户意图）。
- **姿势手势的匹配必须在 `_apply_drive_params` 之前**（量程按原始角度定；录制与匹配
  得吃同一份数据），顺序已用 AST 断言钉死，别挪。
- 重建 Qt 控件网格必须 `layout.removeWidget()` **再**删，只 `setParent(None)` 会让
  布局项堆积（格子越涨越多）。
- 手臂两杆 IK 的**肘位挑选不能硬切**：两条先验（肘在肩下 / 更靠外）切换的那一点上
  两支解能差上百度，硬切会让手穿过肩水平线时上臂整条翻过去。用 `tanh` 软判据 +
  连续权重插值（见手册 3.1）。
- **不要再引入「拿上一帧角度当参考来绕角」的逻辑**（原 `_unwrap` 已删：它拿被钳位过
  的平滑值当参考，钳过一次就偏 180°+，手臂永久卡住）。
- VRM 绑定姿态逐模型不同，**旋转角绝不能写死**；世界旋转必须转成骨骼局部坐标系再乘进
  glTF 局部矩阵。

## 自检（不需要摄像头 / 麦克风，改完必跑）

`tools/` 下 gesture / gesture_actions / hand_drive / lipsync / pose_gesture / vrm_arm
六个 `_selftest.py` + `QT_QPA_PLATFORM=offscreen` 的 `ui_smoke_test.py`，**7 个全要
exit 0**（命令见技能 `xingxian-client-selftest`）。

当前基线（全绿）：gesture 28 / gesture_actions 177 / hand_drive 33 / lipsync 22 /
pose_gesture 76 / vrm_arm 176 / ui_smoke OK。看界面用 `tools/preview_motion_page.py`
（渲手势卡片 PNG；离屏无字体，只见布局）。

## 环境

- 本机 bash 是 PortableGit shim，**没有 coreutils**（`ls`/`cat`/`tail`/`grep` 都不可
  用），用 Read / Glob / Grep 或 `python -c`。venv：`client-python/.venv/Scripts/python.exe`。
- 回归样本模型在 `材料/`。UI 可无窗口端到端（`HomeWindow.__new__` 绕开 `__init__`，
  见 `tools/ui_smoke_test.py`）。
