# Graduation Client

星弦客户端登录页，包含高清二次元星空纯背景、透明登录菜单、高清星弦 logo 和 ICO 窗口图标。

- 本地账号下拉切换，每个账号右侧带 × 删除
- 记住密码、自动登录选项
- 忘记密码、注册入口
- 登录时请求 Java 服务端验证账号

登录成功后保存用户名，下次打开自动显示上次登录账号；本地数据保存在用户目录的 `.star_string/accounts.json` 中。

![登录页预览](docs/login_preview.png)

## Requirements

- Python 3.10+
- PySide6 6.11.2
- live2d-py 0.7.0.4（Cubism 3+ Live2D 模型渲染）
- PyOpenGL、Pillow、numpy

## 首页与虚拟形象

- 登录成功后进入工作台首页，左侧导航可切换视频动捕、音频变声、虚拟形象、模型管理等页面。
- 「虚拟形象」页会加载当前启用的 Live2D 模型并实时绘制（透明背景、自动眨眼/呼吸、闲置动作、鼠标拖拽跟随）。
- Live2D 模型在「模型管理」里导入（支持 `.model3.json`、`.zip` 或模型文件夹），导入后点击「使用」即可启用。
- 每个账户的数据相互隔离：模型文件与注册表保存在 `~/.star_string/accounts_data/<账户名>/models/` 与 `models.json`，不同账户互不影响。首次使用时会自动把旧的全局模型迁移到当前登录账户。

## 服务器地址

修改 `.env` 中的 `SERVER_BASE_URL` 即可切换服务器地址：

```text
SERVER_BASE_URL=http://127.0.0.1:8080
```

## Run

```bash
cd client-python
python -m app.main
```

默认账号：

```text
用户名：admin
密码：123456
```

当前机器使用 MSYS2 Python 时，可以改用：

```bash
pacman -S mingw-w64-ucrt-x86_64-pyside6
```

## 素材来源

- 高清星空背景来自 Alpha Coders，仅用于个人非商业用途：
  `https://alphacoders.com/anime-night-wallpapers`
- 登录页使用的 logo 和 ICO 由 `星弦logo设计.png` 生成。
