# Design: exibir e baixar o log completo de processamento do job

## Contexto

Quando um job de processamento SPED termina — seja com sucesso total, sucesso
parcial (algumas antecipações da planilha não casaram com nenhuma NF do SPED)
ou falha total (nenhuma antecipação casou) — o backend já registra, em
`JobLog`, uma entrada por etapa do processamento, incluindo uma linha WARN
por antecipação sem correspondência (NF, série, CNPJ, tipo — ver
`app/workers/tasks.py`, bloco `if unmatched:`).

Hoje esse detalhe é invisível pro usuário: a tela `processar` (frontend) só
mostra `job.error_message` (uma frase genérica) no caso de falha, e nada no
caso de sucesso — mesmo quando o sucesso é parcial (algumas antecipações
ficaram de fora). O endpoint `GET /jobs/{id}/logs` já existe e já devolve
todas essas entradas, mas nunca é chamado pelo frontend.

## Objetivo

Sempre que o job terminar (sucesso ou falha), o usuário deve conseguir ver e
baixar o log completo do processamento — incluindo, em destaque, quais
antecipações da planilha não foram associadas a nenhuma NF do SPED e por quê.

## Escopo

Mudança **só no frontend** (`frontend/src/app/(dashboard)/processar/page.tsx`).
Nenhuma mudança de backend é necessária — `GET /jobs/{id}/logs` já expõe
tudo que é preciso (nível, mensagem, timestamp, para qualquer status de job).

## Fluxo de dados

1. A tela já faz polling de `GET /jobs/{id}` a cada 3s enquanto `step ===
   "processing"`, até o status virar `COMPLETED` ou `FAILED`.
2. No momento em que esse polling detecta um desses dois status finais, faz
   **uma chamada adicional** a `GET /jobs/{id}/logs` e guarda o resultado em
   estado local (`jobLogs: JobLogEntry[]`).
3. Se essa chamada falhar (raro — o job já existe e pertence ao usuário
   nesse ponto), a seção de log simplesmente não aparece; o resto da tela
   (stats de sucesso, ou mensagem de erro) continua funcionando normalmente.

## Apresentação na UI

- **Tela de sucesso (`step === "done"`):** abaixo dos stats existentes, uma
  seção colapsável **"Ver log completo do processamento"**, fechada por
  padrão (não polui a tela quando está tudo certo). Ao expandir, lista cada
  entrada do log em ordem cronológica, com cor por nível (INFO cinza, WARN
  amarelo, ERROR vermelho). Um botão **"Baixar log (.txt)"** sempre visível,
  independente da seção estar expandida.
- **Tela de erro (`step === "error"`):** o log aparece **expandido por
  padrão** (é o motivo de a pessoa estar ali), no lugar de/complementando a
  frase única de `job.error_message` atual. Mesmo botão de download.

## Formato do arquivo baixado

Gerado inteiramente no navegador (via `Blob` + `URL.createObjectURL`, sem
endpoint novo) a partir do array já buscado em `jobLogs`. Uma linha por
entrada, texto simples:

```
[14:32:10] INFO  Processamento iniciado
[14:32:11] INFO  Arquivo sped recebido: SPED00001_07_2026.txt (2453 KB)
[14:32:15] WARN  Sem correspondência no SPED: NF 12345 série 1 CNPJ 12345678000199 tipo NORMAL
[14:32:20] ERROR Nenhuma antecipação da planilha foi associada a uma nota fiscal do SPED
```

Nome do arquivo: `log_job_<primeiros 8 caracteres do job id>.txt` — mesmo
padrão já usado pelo SPED de saída (`sped_enriquecido_<id8>.txt`).

## Fora de escopo

- Nenhuma mudança no formato/conteúdo dos `JobLog` gravados pelo backend —
  eles já têm tudo que essa feature precisa.
- Nenhum endpoint novo — reaproveita `GET /jobs/{id}/logs`.
- Paginação/limite de entradas no log: os jobs processam algumas centenas de
  NFs no máximo; o volume de linhas de log é pequeno o suficiente pra não
  precisar de paginação.
