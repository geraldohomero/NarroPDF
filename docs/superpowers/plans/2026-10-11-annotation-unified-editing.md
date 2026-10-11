# Unified Annotations & Interactive Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide unified multi-line PDF annotations (highlights and underlines), hit-test selection of existing annotations, interactive two-ended drag handles for expanding/contracting selections, deletion and color changing via a floating popover, and rebuild/reinstall the Flatpak application.

**Architecture:** PyMuPDF multi-quad annotation creation/replacement in `src/annotations.py`, word-range mapping in `src/text_selection.py`, Cairo overlay handle rendering in `src/window/annotations.py`, gesture interaction in `src/window/navigation.py`, and contextual actions in `src/window/ui.py`.

**Tech Stack:** Python 3.12, PyMuPDF (fitz), GTK 4, Libadwaita, Cairo, Flatpak Builder.

**Spec:** `docs/superpowers/specs/2026-10-11-annotation-unified-editing-design.md`

## Global Constraints

- Python 3.12 running inside GNOME 49 Flatpak environment.
- Multi-line highlights and underlines must create exactly 1 `fitz.Annot` with quads covering all lines.
- PyMuPDF annotations do not support `annot.vertices = ...`, so resizing replaces the annotation atomically via delete + re-add with new quads while preserving type, stroke color, and opacity.
- Selected annotation visual handles must be drawn in Cairo with accent blue (`#3584e4`) fill and white border at the start word top-left and end word bottom-right.
- Selected annotation popover must offer Delete (`user-trash-symbolic`) and Color selection.
- All tests in `tests/` must pass via `flatpak run --command=python3 org.geraldohomero.NarroPdf -m unittest discover tests`.
- The Flatpak must be built and reinstalled locally via `flatpak run org.flatpak.Builder --user --install --force-clean build-dir org.geraldohomero.NarroPdf.yaml` and the bundle file updated.

## Review Focus

- Multi-line highlight with 3+ lines produces exactly 1 annotation object whose vertices contain 12 points (3 quads) instead of 3 separate annotations.
- Clicking an existing highlight or underline accurately selects it and maps to the correct start and end word indices.
- Dragging the start handle backwards or forwards alters only the start word index and clamps at `end_word_index`.
- Dragging the end handle backwards or forwards alters only the end word index and clamps at `start_word_index`.
- Deleting an annotation completely removes it from the PDF page, updates unsaved state, and refreshes the canvas.

---

### Task 1: Unified Multi-line Annotations & PyMuPDF Helpers in `src/annotations.py`

**Files:**
- Modify: `src/annotations.py:20-78`
- Create: `tests/test_annotations.py`

**Interfaces:**
- Consumes: `fitz.Page`, `AnnotationType`, `line_rects: list[fitz.Rect]`, `color: tuple[float, float, float]`, `opacity: float`
- Produces:
  - `AnnotationManager.apply(page, annotation_type, line_rects, color, opacity) -> tuple[str, list[int]]` (single xref in list for highlight/underline)
  - `AnnotationManager.find_at_point(page: fitz.Page, point: fitz.Point | tuple[float, float]) -> fitz.Annot | None`
  - `AnnotationManager.update_geometry(page: fitz.Page, annot: fitz.Annot, new_line_rects: list[fitz.Rect]) -> fitz.Annot`
  - `AnnotationManager.delete_annot(page: fitz.Page, annot: fitz.Annot) -> bool`

- [ ] **Step 1: Write the failing tests in `tests/test_annotations.py`**

```python
import unittest
import fitz
from src.constants import AnnotationType
from src.annotations import AnnotationManager

class TestAnnotationManager(unittest.TestCase):
    def setUp(self):
        self.doc = fitz.open()
        self.page = self.doc.new_page()

    def test_unified_multi_line_highlight(self):
        r1 = fitz.Rect(50, 50, 200, 65)
        r2 = fitz.Rect(50, 70, 250, 85)
        label, xrefs = AnnotationManager.apply(
            self.page, AnnotationType.HIGHLIGHT, [r1, r2], (1.0, 1.0, 0.0), 0.8
        )
        self.assertEqual(label, "Highlight")
        self.assertEqual(len(xrefs), 1)
        annots = list(self.page.annots())
        self.assertEqual(len(annots), 1)
        self.assertEqual(len(annots[0].vertices), 8)

    def test_find_at_point(self):
        r = fitz.Rect(50, 50, 200, 65)
        AnnotationManager.apply(self.page, AnnotationType.HIGHLIGHT, [r], (1.0, 1.0, 0.0))
        hit = AnnotationManager.find_at_point(self.page, (100, 55))
        self.assertIsNotNone(hit)
        miss = AnnotationManager.find_at_point(self.page, (300, 300))
        self.assertIsNone(miss)

    def test_update_geometry(self):
        r1 = fitz.Rect(50, 50, 200, 65)
        _, xrefs = AnnotationManager.apply(self.page, AnnotationType.HIGHLIGHT, [r1], (0.0, 1.0, 0.0), 0.7)
        annot = self.page.first_annot
        r_new = [fitz.Rect(50, 50, 200, 65), fitz.Rect(50, 70, 250, 85)]
        new_annot = AnnotationManager.update_geometry(self.page, annot, r_new)
        self.assertIsNotNone(new_annot)
        self.assertEqual(len(new_annot.vertices), 8)
        self.assertEqual(len(list(self.page.annots())), 1)

    def test_delete_annot(self):
        r = fitz.Rect(50, 50, 200, 65)
        AnnotationManager.apply(self.page, AnnotationType.HIGHLIGHT, [r], (1.0, 1.0, 0.0))
        annot = self.page.first_annot
        success = AnnotationManager.delete_annot(self.page, annot)
        self.assertTrue(success)
        self.assertEqual(len(list(self.page.annots())), 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `flatpak run --command=python3 org.geraldohomero.NarroPdf -m unittest tests/test_annotations.py`
Expected: FAIL (AttributeError: find_at_point, update_geometry, delete_annot, or multiple xrefs returned)

- [ ] **Step 3: Implement unified creation and helpers in `src/annotations.py`**

Implement:
1. `quads = [rect.quad for rect in line_rects]` and pass `quads` to `page.add_highlight_annot` and `page.add_underline_annot`. Return `[annot.xref]`.
2. `find_at_point(page, point)`: check point containment in `annot.rect` and quad rects from `annot.vertices`.
3. `update_geometry(page, annot, new_line_rects)`: retrieve stroke color, opacity, annot type, remove old annot, create new annot with `new_line_rects` quads, restore properties, return new annot.
4. `delete_annot(page, annot)`: call `page.delete_annot(annot)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `flatpak run --command=python3 org.geraldohomero.NarroPdf -m unittest tests/test_annotations.py`
Expected: PASS (4 tests passing)

- [ ] **Step 5: Commit**

```bash
git add src/annotations.py tests/test_annotations.py
git commit -m "feat: implement unified multi-line annotations and PyMuPDF helper methods"
```

---

### Task 2: Word Range Mapping & Handle Geometry in `src/text_selection.py`

**Files:**
- Modify: `src/text_selection.py`
- Create: `tests/test_text_selection.py`

**Interfaces:**
- Consumes: `page_words: list[dict]`, `annot_vertices: list[fitz.Point] | list[tuple[float, float]]`
- Produces:
  - `TextSelectionHandler.find_word_range_for_vertices(vertices: list) -> tuple[int, int] | None`
  - `TextSelectionHandler.set_selection_bounds(lo: int, hi: int) -> None`
  - `TextSelectionHandler.get_handle_positions(zoom: float) -> tuple[tuple[float, float], tuple[float, float]] | None`

- [ ] **Step 1: Write failing tests in `tests/test_text_selection.py`**

```python
import unittest
import fitz
from src.text_selection import TextSelectionHandler

class TestTextSelectionHandles(unittest.TestCase):
    def setUp(self):
        self.handler = TextSelectionHandler()
        self.handler.set_words([
            {"rect": fitz.Rect(10, 10, 50, 20), "text": "Hello", "block": 0, "line": 0, "word": 0},
            {"rect": fitz.Rect(55, 10, 100, 20), "text": "World", "block": 0, "line": 0, "word": 1},
            {"rect": fitz.Rect(10, 30, 80, 40), "text": "Second", "block": 0, "line": 1, "word": 0},
        ])

    def test_find_word_range_for_vertices(self):
        # Quad covering Hello and World
        vertices = [(10, 10), (100, 10), (10, 20), (100, 20)]
        bounds = self.handler.find_word_range_for_vertices(vertices)
        self.assertEqual(bounds, (0, 1))

    def test_set_selection_bounds_and_handle_positions(self):
        self.handler.set_selection_bounds(0, 1)
        self.assertEqual(self.handler.get_selected_bounds(), (0, 1))
        handles = self.handler.get_handle_positions(zoom=2.0)
        self.assertIsNotNone(handles)
        start_pt, end_pt = handles
        # Start handle at top-left of word 0 (10*2, 10*2) = (20, 20)
        self.assertEqual(start_pt, (20.0, 20.0))
        # End handle at bottom-right of word 1 (100*2, 20*2) = (200, 40)
        self.assertEqual(end_pt, (200.0, 40.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `flatpak run --command=python3 org.geraldohomero.NarroPdf -m unittest tests/test_text_selection.py`
Expected: FAIL (AttributeError: find_word_range_for_vertices, set_selection_bounds, get_handle_positions)

- [ ] **Step 3: Implement methods in `src/text_selection.py`**

Implement:
1. `find_word_range_for_vertices(vertices)`: reconstruct quad rects, find min/max index of overlapping words in `self.page_words`.
2. `set_selection_bounds(lo, hi)`: set `self.selection_range = (lo, hi)`.
3. `get_handle_positions(zoom)`: return `((start_w.rect.x0 * zoom, start_w.rect.y0 * zoom), (end_w.rect.x1 * zoom, end_w.rect.y1 * zoom))`.

- [ ] **Step 4: Run test to verify it passes**

Run: `flatpak run --command=python3 org.geraldohomero.NarroPdf -m unittest tests/test_text_selection.py`
Expected: PASS (2 tests passing)

- [ ] **Step 5: Commit**

```bash
git add src/text_selection.py tests/test_text_selection.py
git commit -m "feat: add word range mapping and handle coordinate resolution to TextSelectionHandler"
```

---

### Task 3: Cairo Rendering of Annotation Selection & Handles in `src/window/annotations.py`

**Files:**
- Modify: `src/window/annotations.py:200-280`

**Interfaces:**
- Consumes: `self.selected_annotation`, `self.selection.get_handle_positions(zoom)`
- Produces:
  - `_render_annotation_handles_on_cr(cr: Any, page_idx: int) -> None`
  - `_hit_test_handle(screen_x: float, screen_y: float) -> str | None` ("start", "end", or None)

- [ ] **Step 1: Write helper logic and hit-test function**

Add handle detection helper:
- Given `screen_x`, `screen_y`, compare Euclidean distance squared against start handle center and end handle center.
- Threshold: radius 14px ($14^2 = 196$).
- Return `"start"` if near start handle, `"end"` if near end handle, else `None`.

- [ ] **Step 2: Implement Cairo drawing of circular handles**

In `_render_highlights_on_cr`:
- If an annotation is selected or active:
  - Draw standard selection fill and outline.
  - Call `_render_annotation_handles_on_cr(cr, page_idx)`:
    - Draw Start Handle: circle at `start_pt` with radius 7px. Fill with `#3584e4` (RGB 0.208, 0.518, 0.894), white stroke (1.5px).
    - Draw End Handle: circle at `end_pt` with radius 7px. Fill with `#3584e4`, white stroke (1.5px).

- [ ] **Step 3: Test rendering via unit tests and verify clean imports**

Run: `flatpak run --command=python3 org.geraldohomero.NarroPdf -m unittest discover tests`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/window/annotations.py
git commit -m "feat: add Cairo rendering for annotation selection outline and resize handles"
```

---

### Task 4: Interactive Mouse Gestures for Hit-Testing & Handle Resizing in `src/window/navigation.py`

**Files:**
- Modify: `src/window/navigation.py:214-323`

**Interfaces:**
- Consumes: `AnnotationManager.find_at_point`, `_hit_test_handle`, `TextSelectionHandler`
- Produces:
  - Handle drag tracking (`_handle_drag_mode`: `"start"` | `"end"` | `None`)
  - Live preview update of start/end bounds during drag
  - Atomic annotation geometry update in PyMuPDF on drag end

- [ ] **Step 1: Update Single Page & Continuous Page Click Handlers**

In `_on_single_click_pressed` and `_on_continuous_click_pressed`:
- When `n_press == 1`:
  - Check `AnnotationManager.find_at_point(page, (x / zoom, y / zoom))`.
  - If hit:
    - Locate covered word range using `self.selection.find_word_range_for_vertices(hit.vertices)`.
    - If words found:
      - Set `self.selected_annotation = {"page_idx": page_idx, "annot": hit, "xref": hit.xref, "bounds": (lo, hi)}`.
      - Set `self.selection.set_selection_bounds(lo, hi)`.
      - Show selection popover with Delete and Color buttons.
      - Queue redraw of drawing area.
      - Return early so selection is not cleared.
  - If not hit:
    - Clear `self.selected_annotation = None`.
    - Clear selection and popdown popover.

- [ ] **Step 2: Update Drag Begin / Update / End Handlers**

In drag callbacks:
- On `drag_begin`:
  - If `self.selected_annotation`:
    - Call `_hit_test_handle(start_x, start_y)`.
    - If `"start"`: `self._handle_drag_mode = "start"`; return.
    - If `"end"`: `self._handle_drag_mode = "end"`; return.
  - Else: normal text drag begin.
- On `drag_update`:
  - If `self._handle_drag_mode == "start"`:
    - Find word under `(start_x + offset_x, start_y + offset_y)`.
    - Constrain: `new_lo <= end_idx`.
    - Update `self.selection.set_selection_bounds(new_lo, end_idx)`.
    - Queue redraw.
  - If `self._handle_drag_mode == "end"`:
    - Find word under `(start_x + offset_x, start_y + offset_y)`.
    - Constrain: `new_hi >= start_idx`.
    - Update `self.selection.set_selection_bounds(start_idx, new_hi)`.
    - Queue redraw.
- On `drag_end`:
  - If `self._handle_drag_mode`:
    - Retrieve updated line rects: `line_rects = self.selection.get_selected_line_rects()`.
    - Call `AnnotationManager.update_geometry(page, self.selected_annotation["annot"], line_rects)`.
    - Update `self.selected_annotation["annot"] = new_annot`.
    - Set `self.has_unsaved_changes = True`.
    - Refresh view (`self._render_view()`).
    - Show popover at updated handle position.
    - Reset `self._handle_drag_mode = None`.

- [ ] **Step 3: Run existing and new tests**

Run: `flatpak run --command=python3 org.geraldohomero.NarroPdf -m unittest discover tests`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/window/navigation.py
git commit -m "feat: implement annotation hit-testing and bidirectional handle drag gestures"
```

---

### Task 5: Annotation Popover Actions (Delete & Color Edit) in `src/window/ui.py` & `src/window/annotations.py`

**Files:**
- Modify: `src/window/ui.py`
- Modify: `src/window/annotations.py`

**Interfaces:**
- Consumes: `self.selected_annotation`, `self.popover`
- Produces:
  - Delete button (`btn_delete_annot`) in popover
  - Color button connected to update existing annotation color

- [ ] **Step 1: Add Delete Button to Selection Popover**

In `src/window/ui.py` (`_build_selection_popover`):
- Add `btn_delete_annot` with icon `user-trash-symbolic`, tooltip "Excluir anotação", style `flat`.
- Connect to `self._on_delete_selected_annotation`.

- [ ] **Step 2: Implement `_on_delete_selected_annotation` in `src/window/annotations.py`**

- If `self.selected_annotation`:
  - Call `AnnotationManager.delete_annot(page, self.selected_annotation["annot"])`.
  - Clear `self.selected_annotation = None`.
  - Clear selection (`self.selection.clear_selection()`).
  - Set `self.has_unsaved_changes = True`.
  - Update save state button.
  - Hide popover.
  - Redraw page and overlay.

- [ ] **Step 3: Update Color change on Selected Annotation**

In `_on_color_changed`:
- If `self.selected_annotation`:
  - Get RGB from `self.current_color`.
  - `annot = self.selected_annotation["annot"]`.
  - `annot.set_colors(stroke=(self.current_color.red, self.current_color.green, self.current_color.blue))`.
  - `annot.set_opacity(self.current_color.alpha)`.
  - `annot.update()`.
  - `self.has_unsaved_changes = True`.
  - `self._render_view()`.

- [ ] **Step 4: Run full test suite**

Run: `flatpak run --command=python3 org.geraldohomero.NarroPdf -m unittest discover tests`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/window/ui.py src/window/annotations.py
git commit -m "feat: add delete button and live color editing to annotation selection popover"
```

---

### Task 6: End-to-End Verification, Flatpak Build and Reinstallation

**Files:**
- Execute build & bundle commands

- [ ] **Step 1: Run complete test suite**

Run: `flatpak run --command=python3 org.geraldohomero.NarroPdf -m unittest discover tests`
Expected: ALL TESTS PASS

- [ ] **Step 2: Rebuild and reinstall Flatpak on user machine**

Run: `flatpak run org.flatpak.Builder --user --install --force-clean build-dir org.geraldohomero.NarroPdf.yaml`
Expected: BUILD AND INSTALL SUCCEED (0 exit code)

- [ ] **Step 3: Update Flatpak standalone bundle**

Run: `flatpak build-bundle ~/.local/share/flatpak/repo org.geraldohomero.NarroPdf.flatpak org.geraldohomero.NarroPdf`
Expected: Bundle created successfully

- [ ] **Step 4: Final verification and commit**

```bash
git status
```
Verify clean git repository.

