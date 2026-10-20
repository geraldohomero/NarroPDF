# NarroPDF

<p align="center">
  <img src="flatpak/logo.png" alt="NarroPDF Logo" width="128"/>
</p>

[English](README.md) | [Português (Brasil)](README.pt-br.md) | [简体中文](README.zh-cn.md)

**NarroPDF** is a modern, minimalist, and accessible PDF reader and annotator built in Python using **GTK4** and **Libadwaita**. It combines advanced document viewing, rich text annotation tools, and an integrated Text-to-Speech (TTS) synthesizer with real-time visual synchronization.

Another Narro application: [Narro Read Selection Aloud](https://github.com/geraldohomero/Narro-Read-Selection-Aloud)

---

## Key Features

- **Integrated Text-to-Speech (TTS)**:
  - Read your PDFs aloud with real-time sentence and word-level visual highlight synchronization.
  - High-quality offline neural voice synthesis powered by **Piper TTS** (default engine).
  - Online natural cloud voice synthesis powered by **Microsoft Edge TTS**.
- **Interactive Playback Controls**:
  - Convenient bottom playback bar and right-side playback panel: play/pause, stop, skip sentence, single-sentence loop, and playback speed adjustment from `0.5x` up to `4.0x`.
  - **Double-click** any sentence directly on the PDF page to start reading immediately from that point.
- **Annotations & Markups**:
  - **Highlight**, **Underline**, and **Notes** with an interactive text entry dialog.
  - Interactive **resize handles** at annotation boundaries to easily adjust selected text coverage.
  - Color picker with predefined opacity levels (`10%`, `25%`, `50%`, `75%`, `80%`, `90%`, and `100%`).
  - Full **Undo / Redo** support (`Ctrl+Z`, `Ctrl+Shift+Z` / `Ctrl+Y`) for creating, resizing, color styling, and deleting annotations.
- **Comprehensive Left Sidebar**:
  - **Pages Tab**: Chronological page list with clear singular page indicators.
  - **Chapters Tab**: Hierarchical document Table of Contents (TOC) with multi-level indentation.
  - **Annotations Tab**: Consolidated list of all annotations in the PDF displaying color badge, page number, and text preview. Clicking any annotation scrolls precisely to its position on the page and selects it, with bidirectional selection synchronization between the PDF document and sidebar list.
- **Smart Reading & Usability**:
  - Continuous scrolling and single page view modes.
  - Smooth Hand Mode (`Ctrl+1`) with Drag-to-Scroll navigation.
  - Smart hyphenation joining across line breaks and margins/page number filtering for clean, natural speech flow.
  - Automatic and silent document language detection.
  - In-document text search (`Ctrl+F`) with real-time match count and quick navigation.
  - Copy selected text to clipboard (`Ctrl+C`).
- **Keyboard Shortcuts**:
  - `Ctrl + 4`: Selection Mode
  - `Ctrl + 1`: Hand Mode (Drag-to-Scroll)
  - `1`: Highlight Tool
  - `2`: Underline Tool
  - `3`: Add Note Tool
  - `Ctrl + C`: Copy selected text
  - `Ctrl + Z`: Undo action
  - `Ctrl + Shift + Z` / `Ctrl + Y`: Redo action
  - `Ctrl + F`: Search in document
  - `Ctrl + O`: Open PDF
  - `Ctrl + S`: Save PDF changes
  - `Space`: Play / Pause speech synthesis
- **Modern Interface & Safety**:
  - Built strictly following GNOME design guidelines (Libadwaita), with native support for system light and dark themes.
  - Safe exit protection: warns and prompts to save if there are unsaved annotation changes.

![Application main window](main-window.png)

---

## Installation & Running

### Prerequisites (Local)

Ensure you have Python 3.10+ installed on your Linux system. Install the required system packages and Python dependencies:

```bash
# System packages for Fedora / RHEL:
sudo dnf install python3-gobject gtk4 libadwaita mpv libmpv

# System packages for Debian / Ubuntu:
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libmpv-dev mpv

# Python packages:
pip install -r requirements.txt
```

### Running Locally

```bash
python3 narro-pdf.py
```

---

## Flatpak Packaging

The project is fully configured to be built and distributed via **Flatpak**, following GNOME ecosystem best practices and visual design standards.

### 1. Build and Run Locally (Development Mode)

```bash
# Build the application
flatpak-builder --force-clean build-dir org.geraldohomero.NarroPdf.yaml

# Run the built application
flatpak-builder --run build-dir org.geraldohomero.NarroPdf.yaml org.geraldohomero.NarroPdf
```

### 2. Generate Standalone Installer (`.flatpak` Bundle)

To generate a standalone, single-file `.flatpak` bundle that can be distributed and installed offline:

```bash
# 1. Build and export to a local repository
flatpak-builder --repo=repo --force-clean build-dir org.geraldohomero.NarroPdf.yaml

# 2. Create the bundle package (.flatpak)
flatpak build-bundle repo org.geraldohomero.NarroPdf.flatpak org.geraldohomero.NarroPdf
```

### 3. Install the Generated `.flatpak` File

```bash
flatpak install --user org.geraldohomero.NarroPdf.flatpak
```

---

## App Icon Design (Flatpak & GNOME Guidelines)

The application icon aligns with the **GNOME / Flatpak** app icon specifications:
- Symmetrical *squircle* base in Adwaita blue.
- Centered folded-paper illustration (representing the PDF document) integrated with a speaker symbol.
- Transparent background for seamless adaptation across various system docks and themes.

---

## License

This project is licensed under the terms specified in the repository. Please refer to the source code files for further details.
