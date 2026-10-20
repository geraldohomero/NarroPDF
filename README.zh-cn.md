# NarroPDF

<p align="center">
  <img src="flatpak/logo.png" alt="NarroPDF Logo" width="128"/>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README.pt-br.md">Português (Brasil)</a> | <a href="README.zh-cn.md">简体中文</a>
</p>

**NarroPDF** 是一款现代、简约且注重无障碍体验的 PDF 阅读与批注工具，使用 Python 基于 **GTK4** 和 **Libadwaita** 库开发。它将先进的文档浏览、全套批注工具以及集成的实时同步文本转语音（Text-to-Speech, TTS）朗读功能融为一体。

另一个 Narro 应用：[Narro Read Selection Aloud](https://github.com/geraldohomero/Narro-Read-Selection-Aloud)

---

## 主要功能

- **集成文本转语音（TTS）朗读**：
  - 朗读 PDF 全文，并在界面上实时高亮同步当前正在朗读的句子和词语。
  - 默认采用基于 **Piper TTS** 的本地离线高质量神经网络语音合成引擎。
  - 支持通过 **Microsoft Edge TTS** 使用自然流畅的在线云端语音。
- **交互式朗读播放控制**：
  - 底部播放工具栏与右侧播放控制面板：支持播放/暂停、停止、上一句/下一句跳转、单句循环播放以及 `0.5x` 至 `4.0x` 语速无级调节。
  - **双击** PDF 中的任意句子，即可立即从该句子开始朗读。
- **标注与高亮**：
  - 支持**高亮 (Highlight)**、**下划线 (Underline)** 以及带有交互式输入弹窗的**笔记 (Notes)**。
  - 标注起始端和末端配有交互式**调整手柄**，拖动手柄即可轻松微调选区文本范围。
  - 自定义调色板，支持预设不透明度选择（`10%`、`25%`、`50%`、`75%`、`80%`、`90%` 与 `100%`）。
  - 完整的**撤销与重做**支持（`Ctrl+Z`、`Ctrl+Shift+Z` / `Ctrl+Y`），涵盖创建标注、调整尺寸、更改颜色以及删除标注等全流程操作。
- **功能完备的左侧边栏**：
  - **页面标签页**：按顺序列出全部文档页面，标注清晰直观。
  - **目录标签页**：支持多级层级缩进的大纲与章节导航（TOC）。
  - **标注标签页**：集中汇总当前文档中的所有标注，显示颜色圆点、页码及文本预览。在列表中点击任意标注，视图将精准滚动至对应位置并自动选中，同时支持文档页面与侧边栏列表的双向选中同步。
- **智能阅读与实用工具**：
  - 支持连续滚动视图与单页视图模式。
  - 抓手模式（`Ctrl+1`）下平滑流畅的拖拽滚屏（Drag-to-Scroll）浏览体验。
  - 智能合并跨行连字符单词，自动过滤页眉、页脚及页码杂音，确保语音朗读连贯自然。
  - 自动静默检测文档语言。
  - 文档内文本搜索（`Ctrl+F`），实时高亮显示匹配数量并支持快速跳转。
  - 快速复制选中文本至剪贴板（`Ctrl+C`）。
- **快捷键**：
  - `Ctrl + 4`：选择模式
  - `Ctrl + 1`：抓手模式（拖拽滚屏）
  - `1`：高亮工具（Highlight）
  - `2`：下划线工具（Underline）
  - `3`：添加笔记工具（Note）
  - `Ctrl + C`：复制选中文本
  - `Ctrl + Z`：撤销操作
  - `Ctrl + Shift + Z` / `Ctrl + Y`：重做操作
  - `Ctrl + F`：在文档中查找
  - `Ctrl + O`：打开 PDF 文件
  - `Ctrl + S`：保存 PDF 修改
  - `空格键`：播放 / 暂停语音朗读
- **现代界面与安全保护**：
  - 严格遵循 GNOME (Libadwaita) 人机交互指南设计，自适应窗口布局，原生支持系统浅色与深色主题。
  - 关闭确认保护：当文档存在尚未保存的修改时，退出前会弹出确认对话框提示保存。

![Application main window](main-window.png)

---

## 安装与运行

### 本地环境预备条件

确保您的 Linux 系统中已安装 Python 3.10+。请安装相应的系统依赖库和 Python 依赖包：

```bash
# Fedora / RHEL 系统依赖：
sudo dnf install python3-gobject gtk4 libadwaita mpv libmpv

# Debian / Ubuntu 系统依赖：
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libmpv-dev mpv

# 安装 Python 依赖：
pip install -r requirements.txt
```

### 本地直接运行

```bash
python3 narro-pdf.py
```

---

## Flatpak 打包

本项目已完整配置为支持通过 **Flatpak** 进行构建与分发，遵循 GNOME 生态系统的最佳实践与视觉设计规范。

### 1. 本地构建与运行（开发模式）

```bash
# 构建应用
flatpak-builder --force-clean build-dir org.geraldohomero.NarroPdf.yaml

# 运行构建好的应用
flatpak-builder --run build-dir org.geraldohomero.NarroPdf.yaml org.geraldohomero.NarroPdf
```

### 2. 生成独立安装包（`.flatpak` Bundle）

生成单个可分发的 `.flatpak` 离线安装包：

```bash
# 1. 构建并导出至本地仓库
flatpak-builder --repo=repo --force-clean build-dir org.geraldohomero.NarroPdf.yaml

# 2. 生成 bundle 离线安装包 (.flatpak)
flatpak build-bundle repo org.geraldohomero.NarroPdf.flatpak org.geraldohomero.NarroPdf
```

### 3. 安装生成的 `.flatpak` 安装包

```bash
flatpak install --user org.geraldohomero.NarroPdf.flatpak
```

---

## 图标设计（遵循 Flatpak & GNOME 规范）

应用图标遵循 **GNOME / Flatpak** 应用图标设计规范：
- 采用 Adwaita 经典蓝色的 *squircle*（圆角矩形）基底。
- 居中呈现折角纸张插画（象征 PDF 文档）并融合扬声器喇叭符号。
- 采用透明背景，自然融入各 Linux 发行版系统的不同主题风格与任务栏。

---

## 开源许可

本项目遵循本仓库中注明的开源许可协议。详细信息请参阅源代码文件。
