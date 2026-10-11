# Design Document: Sincronização e Destaque Duplo de Leitura em Voz Alta (TTS)

- **Data**: 2026-10-10
- **Status**: Aprovado
- **Autor**: Antigravity & NarroPDF Team
- **Escopo**: Subsistema de TTS com Destaque Visual Sincronizado Frase a Frase e Palavra por Palavra, Controles de Navegação e Auto-Scroll.

---

## 1. Visão Geral e Objetivos

O objetivo deste projeto é implementar no **NarroPDF** uma experiência de leitura em voz alta acessível, fluida e visualmente sincronizada (inspirada no aplicativo *Readest*).

### Objetivos Principais
1. **Destaque Duplo em Tempo Real**:
   - Destacar com fundo suave toda a sentença atualmente em reprodução.
   - Destacar de forma vívida e precisa cada palavra no momento exato em que é pronunciada.
2. **Sincronização Áudio-Visual**:
   - Capturar metadados temporais (`WordBoundary`) com precisão de milissegundos via Edge TTS (e interpolação proporcional para Piper TTS).
   - Manter um relógio de reprodução contínuo via socket IPC do `mpv` a ~40–60 FPS.
3. **Pipeline de Reprodução Contínua com Pré-buffer**:
   - Processamento de frases com fila assíncrona e pré-carregamento da próxima sentença, eliminando pausas perceptíveis entre frases.
   - Avanço automático de página e rolagem suave (auto-scroll) para manter a leitura sempre visível.
4. **Navegação Intuitiva e Controles Visuais**:
   - Botões na barra de reprodução para avançar/retroceder por **Frase** e por **Parágrafo**.
   - Indicador textual de progresso (ex: `Frase 3 de 15 • Pág 2 de 10`).
   - Gesto de duplo clique em qualquer palavra no PDF para iniciar ou saltar a leitura imediatamente a partir dali.

---

## 2. Arquitetura do Sistema

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Segmentador de Texto (src/tts_segmenter.py)                         │
│    PyMuPDF -> Blocos / Linhas -> Sentenças -> Palavras com fitz.Rect   │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. Coordenador de TTS e Fila (src/tts_coordinator.py)                 │
│    - Fila de sentenças com pré-carregamento (lookahead)                │
│    - Edge TTS com boundary="WordBoundary" / Piper interpolado          │
│    - Gestão do processo mpv e envio de áudio                           │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. Relógio de Áudio & Sincronização (Audio Clock via mpv IPC)          │
│    - GLib.timeout_add (~25ms) consulta time-pos no socket UNIX mpv     │
│    - Busca binária (bisect) localiza a palavra ativa no tempo atual   │
│    - Emite callbacks de atualização (page_idx, sentence_idx, word_idx) │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 4. Camada Visual & Interação (src/window/annotations.py & ui.py)       │
│    - Cairo DrawingArea desenha retângulos de frase e palavra           │
│    - Auto-scroll ajusta vadjustment no GtkScrolledWindow               │
│    - Controles de playback: Anterior/Próximo (Frase e Parágrafo)       │
│    - Clique duplo no GtkGestureClick salta reprodução para a palavra   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Modelos e Estruturas de Dados

Criado em `src/tts_segmenter.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field
import fitz

@dataclass
class TtsWord:
    """Representa uma palavra extraída do PDF com suas coordenadas originais."""
    text: str
    rect: fitz.Rect
    word_index: int
    char_start: int
    char_end: int

@dataclass
class TtsSentence:
    """Representa uma frase lógica composta por palavras contíguas."""
    page_index: int
    paragraph_index: int
    sentence_index: int
    text: str
    words: list[TtsWord]
    line_rects: list[fitz.Rect] = field(default_factory=list)

@dataclass
class TtsParagraph:
    """Representa um parágrafo estrutural (bloco PyMuPDF)."""
    page_index: int
    paragraph_index: int
    sentences: list[TtsSentence]

@dataclass
class WordBoundaryInfo:
    """Informação de tempo de uma palavra sintetizada."""
    time: float      # Tempo de início em segundos
    duration: float  # Duração em segundos
    text: str
    word_index: int  # Índice correspondente na TtsSentence
```

---

## 4. Segmentação Semântica de Texto (`src/tts_segmenter.py`)

1. **Extração das Palavras**:
   - `page.get_text("words")` retorna tuplas `(x0, y0, x1, y1, text, block_no, line_no, word_no)`.
   - Palavras são agrupadas por `block_no` em parágrafos.
2. **Identificação de Frases**:
   - Dentro de cada parágrafo, as palavras são reunidas com seus devidos espaços.
   - Uma regex de delimitação de sentenças identifica finais de frase:
     `r'([.!?…]+["\')\]»]*)(?:\s+|$)'`
   - O mapeamento preserva o intervalo de caracteres `[char_start, char_end]` de cada palavra em relação ao texto da frase.
3. **Agrupamento de Linhas (Line Rectangles)**:
   - Para evitar pintar retângulos recortados com gaps, palavras consecutivas da mesma linha são mescladas em um único `fitz.Rect` para compor a lista `line_rects` da sentença.

---

## 5. Síntese e Fila de Pré-carregamento (`src/tts_coordinator.py`)

### 5.1 Síntese com Timestamps
- **Edge TTS**:
  - `edge_tts.Communicate(sentence_text, voice, rate="+0%", boundary="WordBoundary")`.
  - Chunk de áudio é salvo em arquivo temporário `.mp3`.
  - Chunks de tipo `"WordBoundary"` fornecem `offset` (ticks de 100ns) e `duration`.
  - São convertidos para segundos (`offset / 10_000_000`) e alinhados sequencialmente com os objetos `TtsWord` da sentença.
- **Piper TTS**:
  - Execução via subprocess com saída em `.wav`.
  - Duração total é extraída do cabeçalho WAV.
  - Timestamps são distribuídos proporcionalmente ao número de caracteres ponderado de cada palavra na frase.

### 5.2 Fila de Lookahead (Pré-buffer)
- Um worker em background mantém o próximo item `N + 1` preparado em disco.
- Ao término do áudio no `mpv`, a sentença seguinte já está disponível com latência zero de rede.
- Caso o usuário salte para outra frase ou parágrafo, a fila descarta buffers pendentes e prioriza imediatamente a nova posição.

---

## 6. Sincronização do Relógio de Áudio (Audio Clock)

1. **Monitoramento via IPC**:
   - Um timer GTK (`GLib.timeout_add(25, ...)`, ~40 FPS) verifica o status do `mpv`.
   - Comando IPC: `{"command": ["get_property", "time-pos"]}`.
   - Retorno: tempo atual do arquivo em segundos (ex: `1.458`).
2. **Busca Binária (`bisect`)**:
   - A lista de tempos de início `[b.time for b in boundaries]` é consultada via `bisect.bisect_right`.
   - Identifica instantaneamente o índice `active_word_index`.
3. **Disparo de Evento**:
   - Quando o índice da palavra muda, o coordenador aciona o callback da UI:
     `on_word_active(page_idx, sentence_idx, word_idx)`.
   - Apenas a área relevante é repintada via `drawing_area.queue_draw()`.

---

## 7. Renderização Visual no GTK4 / Cairo

Implementado em `src/window/annotations.py` e integrado no pipeline de desenho:

1. **Sentence Highlight**:
   - Cor: Amarelo pastel suave com transparência (`rgba(1.0, 0.90, 0.30, 0.28)`).
   - Desenhado para cada retângulo em `sentence.line_rects`, escalado por `self.renderer.zoom`.
2. **Word Highlight**:
   - Cor: Âmbar vibrante (`rgba(0.98, 0.55, 0.0, 0.85)`) com borda suave ou cor do tema accent Adwaita.
   - Desenhado sobre o `rect` da palavra ativa.
3. **Desempenho**:
   - O Cairo desenha apenas sobre o `Gtk.DrawingArea` que já existe em overlay sobre cada página.
   - Sem impacto na renderização do PDF base (que continua em cache no `Gtk.Picture`).

---

## 8. Auto-Scroll e Navegação de Página

- **Modo Contínuo (`ViewMode.CONTINUOUS`)**:
  - Se os limites verticais da frase ativa estiverem fora da janela visível do `scroller` (ou nos 15% inferiores), o valor de `vadjustment` é animado suavemente para manter a frase a 25% do topo da janela.
- **Modo Página Única (`ViewMode.SINGLE_PAGE`)**:
  - Quando a última frase da página é concluída, o coordenador aciona `_navigate_page(+1)`, carrega as sentenças da nova página e prossegue a leitura automaticamente.

---

## 9. Controles na Interface e Interação

### 9.1 Barra Inferior de Reprodução (`playback_bar`)
Adicionados novos botões e rótulos:
1. `btn_prev_paragraph`: Pula para o início do parágrafo anterior (`go-top-symbolic` ou `media-skip-backward-symbolic`).
2. `btn_prev_sentence`: Pula para a frase anterior (`media-seek-backward-symbolic`).
3. `btn_play_pause`: Alterna entre pausar e retomar a leitura.
4. `btn_next_sentence`: Pula para a próxima frase (`media-seek-forward-symbolic`).
5. `btn_next_paragraph`: Pula para o próximo parágrafo (`go-bottom-symbolic` ou `media-skip-forward-symbolic`).
6. `btn_stop`: Interrompe a leitura e limpa os destaques.
7. `status_label`: Exibe progresso: `Frase X de Y (Pág. Z) • Nome da Voz`.
8. `speed_scale`: Controle dinâmico de velocidade (0.5x a 4.0x).

### 9.2 Clique Duplo no Documento
- O `Gtk.GestureClick` associado à área de desenho escuta evento de duplo clique (`n_press == 2`).
- Converte as coordenadas do clique para pontos do PDF.
- Identifica a palavra e frase atingidas.
- Dispara `read_from_sentence(page_idx, sentence_idx)`.

---

## 10. Tratamento de Erros e Casos de Borda

1. **Páginas sem texto (páginas escaneadas ou vazias)**:
   - Identificadas imediatamente; avança para a próxima página com aviso suave na barra de status.
2. **Queda de conexão durante Edge TTS**:
   - Notifica na barra de status (`"Falha na síntese de áudio. Tentando reconectar..."`) sem travar a interface.
3. **Cancelamento rápido do usuário (Stop ou fechar janela)**:
   - Limpa processos `mpv`, fecha sockets IPC e descarta arquivos temporários em `tempfile`.

---

## 11. Estratégia de Testes e Verificação

1. **Testes Unitários**:
   - `test_segmenter.py`: Testa divisão de texto em parágrafos e frases, verificando que pontuações complexas (`Sr.`, números `3.14`, aspas) não quebram sentenças incorretamente e que as coordenadas das palavras permanecem íntegras.
   - `test_word_boundary_sync.py`: Testa busca binária de timestamps e alinhamento de boundaries.
2. **Testes de Integração e Sistema**:
   - Execução via `flatpak run --command=python3 org.geraldohomero.NarroPdf` ou ambiente local com PDF de teste.
   - Verificação visual dos destaques e navegação por clique duplo e botões da barra.
