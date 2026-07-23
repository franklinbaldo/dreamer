# Product Requirements Document (PRD): Dreamer V2 (2026 Edition)

Este documento define as especificações completas de produto, arquitetura e engenharia para a implementação do **Dreamer V2**. Ele serve como a especificação de referência definitiva para o desenvolvimento do sistema.

---

## 1. Visão Geral e Tese do Produto

O **Dreamer V2** é uma ferramenta de linha de comando (CLI) e workflow local projetada para transformar arquivos de áudio narrativos em storyboards visuais. 

### Tese Principal
A consistência visual e o controle de custos são os pilares essenciais do produto. Ao invés de um gerador de imagem "caixa-preta", o Dreamer V2 é um **workflow editorial reprodutível, revisável e incremental** que permite a intermediação humana e rascunhos de baixo custo antes da renderização final de alta definição.

---

## 2. Requisitos Técnicos e Stack (2026)

* **Linguagem**: Python 3.12+
* **Gerenciador de Dependências**: `uv`
* **Linter & Formatter**: `ruff` (Regras de linting estritas baseadas em `ALL`, com ignores explícitos documentados apenas para conflitos estilísticos e injeções de dependência do Typer).
* **Interface CLI**: `typer` + `rich` para formatação visual no console.
* **SDK GenAI**: Oficial `google-genai` (versão moderna de 2026).
* **Armazenamento de Estado**: SQLite (`run.sqlite`) para rastreamento de execução e banco relacional local, associado a arquivos JSON portáteis para compartilhamento editorial.

---

## 3. Limites e Regras de Negócio do MVP

O escopo inicial do MVP está estritamente limitado para garantir previsibilidade de testes e custos:
* **Duração de Áudio**: Máximo de 20 minutos por execução.
* **Quantidade de Cenas**: Máximo de 30 cenas por projeto.
* **Bíblia Visual (Elementos)**: Limite de até 4 personagens principais e até 10 objetos recorrentes com preservação de identidade.
* **Proporção da Imagem (Aspect Ratio)**: Fixo em `16:9` (1.77) para todas as gerações.
* **Ciclo de Resolução**:
  * Elementos da Bíblia Visual: **1K** (1024x1024 / 1024x576) para preservar o máximo de detalhes de referência.
  * Cenas Draft: **512px** (512x288) para geração rápida e de custo reduzido.
  * Cenas Finais: **2K** (2048x1152) nativo.
  * Resolução **4K** (4096x2304) configurável via flag opcional.

---

## 4. Arquitetura de Dados & Estados

Os arquivos de saída de um projeto devem ser estritamente separados para manter a portabilidade editorial e a integridade do runtime:

```text
meu_projeto/
├── project.toml           # Configuração de modelos, aspect ratio e limites
├── storyboard.json        # Plano editorial (descrições e prompts de cena)
├── visual_bible.json      # Catálogo e referências canônicas de estilo/personagens
├── manifest.json          # Proveniência, hashes do áudio, modelos e parâmetros reais
├── run.sqlite             # Banco de dados operacional: transações, fila de jobs e custos
├── bible/                 # Imagens 1K dos elementos aprovados
│   ├── char_001.png
│   └── obj_001.png
├── drafts/                # Imagens 512px das cenas
│   └── scene_001_draft.png
└── renders/               # Imagens finais 2K/4K
    └── scene_001_final.png
```

### 4.1. Schemas de Dados (Pydantic v2)

```python
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, Field

class ElementKind(StrEnum):
    CHARACTER = "character"
    OBJECT = "object"
    LOCATION = "location"

class Element(BaseModel):
    id: str
    kind: ElementKind
    canonical_description: str
    visual_constraints: list[str] = Field(default_factory=list)
    reference_asset_path: str | None = None

class ScenePlan(BaseModel):
    id: str
    sequence_id: str
    start_ms: int
    end_ms: int
    audio_cue: str = Field(description="Segmento transcrito ou evento de áudio correspondente")
    narrative_purpose: str = Field(description="Objetivo dramático da cena")
    shot_type: str = Field(description="Ex: Wide Shot, Close-up, Extreme Close-up")
    camera_angle: str = Field(description="Ex: High-angle, Eye-level, Dutch Angle")
    lighting: str = Field(description="Ex: Golden hour, High-key, Moody Dark")
    element_ids: list[str] = Field(default_factory=list, description="IDs dos Elementos presentes na cena")
    visual_prompt: str
    continuity_notes: str | None = None
    depends_on_scene_ids: list[str] = Field(default_factory=list, description="Dependências explícitas de continuidade visual")

class ArtifactStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    GENERATED = "generated"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"

class ArtifactState(BaseModel):
    artifact_id: str
    status: ArtifactStatus = ArtifactStatus.PENDING
    path: str | None = None
    content_hash: str | None = None
    error: str | None = None
```

---

## 5. Grafo de Dependências e Cache Inteligente

Para evitar que a alteração de um único detalhe force a regeneração de todas as cenas subsequentes, o Dreamer V2 adota um modelo baseado em dependências explícitas no cache:

1. **Bíblia Visual**: É o nó raiz de identidade.
2. **Sequence Anchor**: O primeiro frame de uma sequência define o cenário, a iluminação e as posições iniciais.
3. **Continuidade Textual**: Cenas subsequentes carregam metadados descritivos em `continuity_notes` em vez de depender da imagem renderizada do frame anterior para sua compilação.
4. **Grafo de Invalidação**:
   * O hash do artefato é derivado de: `SHA-256 do áudio` + `Visual Prompt` + `Model Config` + `Resolutions` + `Hashes das imagens de Elementos ativos`.
   * Se o usuário alterar a referência visual de `char_01`, todas as cenas que possuem `char_01` na lista `element_ids` são invalidadas no cache.
   * Se uma cena `03` tiver dependência explícita em `depends_on_scene_ids: ["02"]` (ex: cena de corte reverso que reaproveita a exata composição), a invalidação de `02` invalidará em cascata a cena `03`.

---

## 6. Interface CLI (Contrato do Usuário)

O Dreamer V2 implementará comandos modulares bem definidos:

* `dreamer init AUDIO_FILE --output PROJECT_DIR`: Cria a estrutura de pastas do projeto, calcula o hash do áudio e gera o `project.toml` base.
* `dreamer analyze PROJECT_DIR`: Executa a análise de áudio (seja via upload ou reconciliação de janelas) e escreve o `storyboard.json` base.
* `dreamer bible PROJECT_DIR`: Gera as referências canônicas da Bíblia Visual em 1K na pasta `bible/` e o arquivo `visual_bible.json`.
* `dreamer review PROJECT_DIR`: Abre a interface de revisão local (servidor web temporário na porta `127.0.0.1:8080`) onde o usuário pode ler a timeline de áudio, ajustar prompts, editar parâmetros e dar "Aprovado/Reprovado" nos Elementos e Cenas.
* `dreamer render PROJECT_DIR --stage [draft|final] [--scene SCENE_ID]`: Executa a renderização das cenas pendentes no nível de resolução solicitado.
* `dreamer resume PROJECT_DIR`: Executa sequencialmente todas as fases inacabadas ou pendentes até o próximo gate de revisão humana.
* `dreamer status PROJECT_DIR`: Apresenta um sumário no terminal das cenas renderizadas, custos correntes de API e integridade do cache.
* `dreamer estimate PROJECT_DIR`: Calcula a estimativa de custos de token de áudio e geração de imagem antes de submeter requisições de render.
* `dreamer export PROJECT_DIR --format [mp4|pdf|otio]`: Compila os arquivos finais de entrega na pasta `exports/`.
* `dreamer run AUDIO_FILE`: Atalho de conveniência que executa `init` -> `analyze` -> `bible` -> inicia a CLI interativa de gate de aprovação.

### Comportamento Operacional:
* **Single-Process Lock**: O Dreamer V2 cria um arquivo de lock `.lock` no diretório do projeto. Se outro processo tentar abrir o mesmo projeto simultaneamente, a execução falhará com Exit Code `10`.
* **Interrupção Graciosa (Ctrl+C)**: Ao receber um sinal de interrupção, o CLI para o processamento assíncrono respeitando as requisições em trânsito por até 5 segundos, salva o estado atual das transações no `run.sqlite` e finaliza com Exit Code `130`.

---

## 7. Controle de Custos e Orçamentação

Para mitigar custos acidentais com múltiplas regenerações de cenas em alta definição, o CLI adota:

1. **Gate Estimativo**: Toda execução de `render` apresentará primeiro o custo total estimado em USD baseado no preço atual da tabela da Google (Draft: \$0,045/img, Final 2K: \$0,101/img). O usuário deve confirmar interativamente digitando `y` para prosseguir no modo padrão.
2. **Teto de Custo**: O parâmetro `--max-cost-usd` (ou configuração correspondente no `project.toml`) define um limite absoluto. A execução de transações no banco de dados operacional SQLite manterá um ledger atualizado em tempo real. Se o teto for alcançado durante o processamento de lotes paralelos, o pipeline aborta graciosamente e notifica o usuário.

---

## 8. Abstração e Provedores

A lógica de pipeline deve depender de protocolos e adaptadores para evitar acoplamentos a APIs específicas que possam depreciar no futuro:

```python
from typing import Protocol, BinaryIO

class AudioAnalyzer(Protocol):
    def analyze(self, audio_data: BinaryIO, config: dict) -> tuple[dict, str]:
        """Retorna os metadados brutos do storyboard analisado e o ID de referência do arquivo remoto."""

class ImageRenderer(Protocol):
    def render_single(self, prompt: str, reference_images: list[str], resolution: str) -> bytes: ...

class BatchImageRenderer(Protocol):
    def render_batch(self, prompts: list[str], reference_images: list[str], resolution: str) -> list[bytes]: ...
```

---

## 9. Privacidade e Ciclo de Vida do Upload

* **Upload Efêmero**: Todos os arquivos de áudio carregados para a Files API do Google serão apagados ativamente pelo pipeline via chamada de exclusão no bloco `finally` da execução de análise.
* **Segurança de Logs**: As chaves de API, transcrições brutas e dados identificáveis do usuário não serão impressos ou armazenados em arquivos de log globais.
* **Opção de Transcrição Local**: O usuário pode configurar no `project.toml` se a transcrição textual gerada a partir do áudio deve ser persistida localmente ou mantida apenas em memória durante a execução do processo.

---

## 10. Critérios de Aceite

### 10.1. Critérios Funcionais
* Uma execução interrompida na cena 15 de 30 deve retomar na cena 16 sem repetir chamadas de imagens concluídas anteriormente.
* Alterar um prompt na cena `05` deve invalidar apenas os arquivos `scene_005_draft.png` e `scene_005_final.png` (e descendentes explícitos de composição em `depends_on_scene_ids`), mantendo o restante do storyboard intacto.
* O MP4 gerado na exportação final deve possuir a exata duração do arquivo de áudio original com tolerância de no máximo 100 milissegundos.
* Modificações nas imagens canônicas na pasta `bible/` devem forçar a re-renderização apenas das cenas configuradas com o ID daquele elemento associado.

### 10.2. Critérios de Qualidade do MVP (Métricas)
Antes de declarar o projeto estável para uso em larga escala, as execuções de teste com os três áudios padrão do repositório devem atender:
* **Taxa de Aprovação de Rascunho**: Pelo menos 80% das cenas geradas no modo draft (512px) devem ser aprovadas pelo revisor sem alteração na Bíblia Visual.
* **Limite de Desperdício**: Média de no máximo 1,25 tentativas de renderização de imagem necessárias por cena aprovada.
* **Acurácia de Consistência**: Avaliação de consistência de personagens (identidade, faces e roupas) de pelo menos 4 em uma escala de 1 a 5.
* **Estabilidade de Operação**: 100% de sucesso na gravação de logs de transação e retomada em testes simulados de interrupção abrupta (kill de processo simulado).
