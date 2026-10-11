# Especificação de Design: Anotações Unificadas, Seleção Interativa, Alças de Redimensionamento e Exclusão

**Data:** 11/10/2026  
**Status:** Aprovado para Planejamento  
**Autor:** Antigravity Pair Programmer & Geraldo Homero  

---

## 1. Visão Geral e Objetivos

Atualmente no NarroPDF:
- Ao destacar ou sublinhar um texto multilinhas, cada linha selecionada é salva como uma anotação independente (`fitz.Annot`) no arquivo PDF.
- O usuário não consegue selecionar diretamente uma anotação existente para excluí-la ou redimensioná-la.

### Objetivos Principais:
1. **Anotação Unificada**: Criar apenas **1 única anotação** no PDF (`fitz.Annot`) por seleção multilinhas, utilizando múltiplos quadpoints (`quads = [rect.quad for rect in line_rects]`).
2. **Seleção de Anotações Existentes**: Permitir clicar sobre qualquer marcação de highlight ou underline existente para selecioná-la.
3. **Alças de Redimensionamento Interativas (Resize Handles)**: Exibir alças circulares nas extremidades (início e fim) da anotação selecionada, permitindo arrastar bidirecionalmente palavra por palavra para expandir ou contrair o destaque.
4. **Exclusão e Troca de Cor**: Exibir um popover contextual contendo botão de exclusão (lixeira) e seletor de cor diretamente sobre a anotação selecionada.
5. **Reinstalação do Flatpak**: Recompilar e reinstalar o pacote Flatpak na máquina do usuário ao término da implementação.

---

## 2. Arquitetura e Componentes

### 2.1. Backend de Anotações (`src/annotations.py`)

1. **Criação Unificada (`AnnotationManager.apply`)**:
   - Em vez de iterar sobre `line_rects` chamando `page.add_highlight_annot(rect)`, extrai `quads = [r.quad for r in line_rects]`.
   - Executa `annot = page.add_highlight_annot(quads)` (ou `page.add_underline_annot(quads)`).
   - Aplica cores e opacidade via `annot.set_colors(stroke=color)` e `annot.set_opacity(opacity)`.
   - Retorna o tipo da anotação e uma lista contendo exatamente um xref: `[annot.xref]`.

2. **Hit-Testing (`AnnotationManager.find_at_point`)**:
   - Para um ponto `(px, py)` no espaço do PDF (`screen_x / zoom`, `screen_y / zoom`), percorre `page.annots()`.
   - Filtra anotações do tipo `fitz.PDF_ANNOT_HIGHLIGHT` (8) e `fitz.PDF_ANNOT_UNDERLINE` (9).
   - Verifica se o ponto está dentro de `annot.rect`. Para precisão máxima com múltiplas linhas, verifica se está contido em qualquer um dos retângulos formados pelos `annot.vertices` (agrupados de 4 em 4 pontos por quad).
   - Retorna o objeto `annot` ou `None`.

3. **Substituição Atômica de Geometria (`AnnotationManager.update_geometry`)**:
   - Como o PyMuPDF não disponibiliza setter para `annot.vertices`, atualizações de coordenadas são feitas de modo atômico:
     1. Obtém cor (`annot.colors["stroke"]`), opacidade (`annot.opacity`) e tipo (`annot.type[0]`).
     2. Remove a anotação antiga: `page.delete_annot(annot)`.
     3. Cria a nova anotação unificada com os novos quads (`page.add_highlight_annot` ou `page.add_underline_annot`).
     4. Restaura cor e opacidade e chama `update()`.
     5. Retorna o novo `fitz.Annot`.

4. **Exclusão de Anotação (`AnnotationManager.delete_annot`)**:
   - Remove com segurança a anotação informada da página.

---

### 2.2. Gestão de Seleção de Palavras (`src/text_selection.py`)

1. **Mapeamento de Anotação para Palavras (`find_word_range_for_annot`)**:
   - Dada uma anotação, encontra todas as palavras em `page_words` cujos retângulos intersectam os retângulos da anotação.
   - Determina o índice da primeira palavra (`start_word_index`) e da última palavra (`end_word_index`).

2. **Controle Manual da Seleção**:
   - Métodos para definir `selection_range = (start_idx, end_idx)` e recuperar as coordenadas exatas das alças de início e fim.

---

### 2.3. Renderização Visual no Cairo (`src/window/annotations.py`)

1. **Estado da Anotação Selecionada**:
   - A janela mantém o estado:
     ```python
     self.selected_annotation: dict | None = {
         "page_idx": int,
         "xref": int,
         "annot_type": int,
         "start_word_index": int,
         "end_word_index": int,
         "color": tuple[float, float, float],
         "opacity": float,
     }
     ```

2. **Desenho das Alças e Contorno (`_render_highlights_on_cr`)**:
   - Se houver anotação selecionada na página atual:
     - Desenha retângulo de seleção suave e contorno azul com estilo acentuado (`#3584e4`).
     - **Alça Inicial (Start Handle)**: Círculo de raio 7px no canto superior esquerdo da primeira palavra (`(x0 * zoom, y0 * zoom)`).
     - **Alça Final (End Handle)**: Círculo de raio 7px no canto inferior direito da última palavra (`(x1 * zoom, y1 * zoom)`).
     - As alças têm preenchimento azul acento (`#3584e4`), borda externa branca de 1.5px e sombra sutil para alto contraste contra fundos claros ou escuros.

---

### 2.4. Interação e Gestos (`src/window/navigation.py`)

1. **Detecção de Clique (`_on_single_click_pressed` e `_on_continuous_click_pressed`)**:
   - Se o clique for simples (`n_press == 1`):
     - Verifica se clicou sobre uma anotação existente via `find_at_point`.
     - **Se clicou na anotação**: Seleciona a anotação, calcula os índices de palavras, desenha as alças e exibe o popover contextual com botão de excluir e cor.
     - **Se clicou fora**: Desmarca a anotação selecionada, limpa a seleção e fecha o popover.

2. **Gestos de Arraste (`_on_single_drag_begin`, `_update`, `_end`)**:
   - **`drag_begin`**:
     - Se há anotação selecionada, calcula distância do clique para o centro da Alça Inicial e da Alça Final.
     - Tolerância de acerto da alça: raio de 14px.
     - Se atingiu a Alça Inicial $\rightarrow$ Modo `DRAG_START_HANDLE`.
     - Se atingiu a Alça Final $\rightarrow$ Modo `DRAG_END_HANDLE`.
     - Caso contrário $\rightarrow$ Inicia nova seleção padrão de texto.
   - **`drag_update`**:
     - Se em modo `DRAG_START_HANDLE`: busca palavra sob o cursor e ajusta `start_word_index` (travado para não ultrapassar `end_word_index`).
     - Se em modo `DRAG_END_HANDLE`: busca palavra sob o cursor e ajusta `end_word_index` (travado para não ficar antes de `start_word_index`).
     - Chama `queue_draw()` para atualização fluida em 60 FPS.
   - **`drag_end`**:
     - Se estava arrastando uma alça: invoca `AnnotationManager.update_geometry()`, atualiza o PDF, marca alterações não salvas (`has_unsaved_changes = True`), redesenha a página de fundo (`_render_view()`) e reposiciona o popover.

---

### 2.5. Popover Contextual de Anotação (`src/window/ui.py`)

1. **Conteúdo do Popover**:
   - **Botão Excluir (Lixeira)**: Ícone `user-trash-symbolic`, estilo destrutivo. Clicar chama `page.delete_annot(annot)`, marca não salvo, fecha popover e atualiza renderização.
   - **Seletor de Cor**: Botão de cor permitindo mudar a cor da anotação selecionada em tempo real.
2. **Posicionamento**: Ancorado dinamicamente na extremidade da anotação (junto à alça final).

---

## 3. Plano de Testes e Validação

1. **Testes Automatizados (`tests/test_annotations.py`)**:
   - Teste de highlight multilinhas gerando 1 único objeto de anotação com múltiplos quads.
   - Teste de underline multilinhas gerando 1 único objeto de anotação.
   - Teste de hit-testing com `find_at_point` acertando dentro do quad e ignorando fora.
   - Teste de substituição atômica de geometria (`update_geometry`).
   - Teste de exclusão de anotação.
2. **Testes de Regressão**:
   - Execução completa da suíte de testes (`python3 -m unittest discover tests`).
3. **Build e Reinstalação Flatpak**:
   - Reconstrução e instalação via `flatpak run org.flatpak.Builder --user --install --force-clean build-dir org.geraldohomero.NarroPdf.yaml`.
   - Atualização do arquivo `.flatpak` em bundle.

---

## 4. Conclusão
O design acima atende a todos os requisitos com arquitetura limpa, desacoplada e compatível com as versões existentes de visualização em página única e contínua do NarroPDF.

