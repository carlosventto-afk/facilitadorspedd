# Fase 1 — Motor SPED EFD ICMS/IPI

Documentação técnica do motor de processamento de antecipações de ICMS para o Pará.
Status: **CONCLUÍDA** | Testes: **36/36 passando** | Data: 2026-06-26

---

## Visão geral

O motor recebe:
1. Um arquivo SPED EFD ICMS/IPI (.txt, latin-1, pipe-delimitado)
2. Uma planilha SEFA-PA (.xls ou .xlsx) com as antecipações de ICMS

E produz:
- O mesmo SPED com registros C197, E111 e E116 inseridos, e E110 atualizado
- Saída válida para importação no Validador SPED (PVA)

---

## Arquitetura: 2 passes por streaming

O arquivo SPED não é carregado na RAM — é processado linha a linha em dois passes:

```
[Pass 1] SpedParser     → SpedIndex (mapa de blocos C100, linha do E110, E111 existentes)
                  ↓
[Matcher]               → list[MatchedAnticipation] (associa antecipações aos blocos)
                  ↓
[Pass 2] SpedEnricher   → arquivo de saída enriquecido
```

### Pass 1 — SpedParser (`sped/parser.py`)

- Lê linha a linha e constrói `SpedIndex`
- Indexa blocos C100 com: `chave_nfe`, `numero_nf`, `serie`, `cod_part`, `ind_oper`, `last_child_line`
- Captura a linha exata do E110 para reescrita no Pass 2
- Registra E111/E116 existentes (para evitar duplicatas)
- **Nota:** Arquivos SPED reais podem iniciar com até 1 MB de bytes nulos (bug de software contábil) — o parser ignora esses bytes naturalmente

### Matcher (`sped/matcher.py`)

- Estratégia 1: match por `chave_nfe` (44 dígitos) — global e único
- Estratégia 2: fallback por `(cnpj_emitente, numero_nf, serie)` — para NFs antigas sem chave
- **Dedup:** se o código C197 já existe no bloco C100, a antecipação é ignorada (não duplica)
- Retorna `(matched, unmatched)`

### Pass 2 — SpedEnricher (`sped/writer.py`)

Streaming de entrada → saída com as seguintes modificações:

| Evento | Ação |
|---|---|
| Linha após `last_child_line` de C100 com match | Injeta C197 |
| Linha do E110 | Reescreve incrementando `VL_DEB_ESP` com total de TODAS as antecipações |
| Imediatamente após E110 (se ESPECIAL > 0) | Injeta/acumula E111 PA020008 |
| E111 PA020008 existente | Pula (valor foi acumulado no passo anterior) |
| Antes do E990 | Injeta E116 (um por antecipação) |
| C990 | Reescreve com +N (quantidade de C197 inseridos) |
| E990 | Reescreve com +N (E116 inseridos ± E111 ajustado) |
| Bloco 9 | Bufferiza inteiro para reprocessar 9900/9990/9999 |

---

## Registros inseridos

### C197 — Ajuste de ICMS por documento fiscal
```
|C197|<cod_ajuste>|<descricao>||<valor>|
```
- Filho direto do bloco C100 de ENTRADA
- Inserido após o último filho existente do bloco

| Tipo | Código | Descrição |
|---|---|---|
| NORMAL (1146) | PA70000010 | ICMS ANTECIPADO NORMAL - ART. 107, ANEXO I, RICMS-PA |
| ESPECIAL (1173) | PA70000008 | ICMS ANTECIPADO ESPECIAL - ART. 114-E, ANEXO I, RICMS-PA |
| CESTA_BASICA (1152) | PA70000011 | ICMS ANTECIPADO CESTA BASICA - ART. 109, ANEXO I, RICMS-PA |

### E110 — Apuração do ICMS
Campo atualizado: **VL_DEB_ESP** (último campo de valor do registro)

```
|E110|...|<VL_DEB_ESP_anterior + soma_total_antecipacoes>|
```

- Recebe a soma de TODAS as antecipações (NORMAL + ESPECIAL + CESTA_BASICA)
- Detecção dinâmica do índice: `len(fields) - 2` (compatível com leiautes v3.x e v4.x)

### E111 — Ajuste de apuração (apenas ESPECIAL)
```
|E111|PA020008|OUTROS CREDITOS - ANTECIPACAO ESPECIAL - ART. 114-E, ANEXO I, RICMS-PA|<valor>|
```
- Gerado apenas quando há antecipações ESPECIAL (COD 1173)
- Se já existe E111 PA020008 no arquivo, o valor é ACUMULADO (não duplica)

### E116 — Obrigação de pagamento
```
|E116|001|<valor>|<DT_VCTO>|<COD_REC>||0|||<MES_REF>|
```
- Um E116 por antecipação
- `COD_REC`: 1146 (NORMAL), 1173 (ESPECIAL), 1152 (CESTA_BASICA)
- `DT_VCTO`: data de vencimento do DARE/DAR (opcional, vazio se não fornecido)

---

## Parser da planilha SEFA-PA (`excel/sefa_parser.py`)

### Formatos suportados

**Formato A** — Produto a produto (~20 colunas):
- Título na linha 0: `"Receita: COD1173 ICMS ANTECIPADO ESPECIAL"`
- Coluna de valor: **TOTAL ESTORNO** (prioridade 10)
- Múltiplas linhas por NF (um produto por linha) → somadas por DANFE

**Formato B** — Nota a nota (~13 colunas):
- Coluna de valor: **ICMS A PAGAR** (prioridade 10)
- Coluna de identificação: **SERIE / NOTA** (ex: `"1/27146"` → serie=1, numero=27146)

### Regras de parsing

1. **Tipo de antecipação**: extraído do título (linha 0) — nunca de uma coluna
   - `"1146"` ou `"cod1146"` → NORMAL
   - `"1173"` ou `"cod1173"` → ESPECIAL
   - `"1152"` ou `"cod1152"` → CESTA_BASICA

2. **Prioridade de colunas**: quando múltiplas colunas mapeiam para o mesmo campo, vence a maior prioridade
   - `TOTAL ESTORNO` (prio 10) > `EXPECTATIVA A PAGAR` (prio 6) > `VALOR ICMS CALC` (prio 3)
   - **Problema real resolvido:** "VALOR ICMS CALC" (sempre 0) estava sendo mapeado antes de "TOTAL ESTORNO" (valor real)

3. **Agregação por DANFE**: linhas com o mesmo DANFE têm seu valor somado em um único `RawAnticipation`

4. **CNPJ do emitente**: extraído da coluna `CNPJ ORIGEM`, ou dos bytes 6-19 da chave NF-e

5. **Suporte a .xls**: usa `pandas + xlrd` (não openpyxl, que não suporta .xls antigo)

---

## CLI

```bash
# Passo único (uma planilha)
python -m app.sped.cli process --sped input.txt --excel antec.xls --out saida.txt

# Dois tipos de antecipação (duas planilhas, dois passes)
python -m app.sped.cli process --sped input.txt --excel plan1.xls --out temp.txt
python -m app.sped.cli process --sped temp.txt  --excel plan2.xls --out saida.txt
```

O segundo passe detecta o E111 já inserido no primeiro e acumula o valor (não duplica).

---

## Arquivos de teste/validação

```
Validacao/
  sped_entrada.txt   — SPED sintético com 5 C100 ENTRADA (NFs reais das planilhas)
  sped_saida.txt     — Output com 5 C197, E110 atualizado, E111 PA020008, 5 E116
```

O `sped_saida.txt` pode ser importado no Validador SPED (PVA) para verificação estrutural.

**Resultado do processamento sintético:**
- C197 inseridos: 5 (um por NF)
- E110 VL_DEB_ESP: R$ 2.749,50 (soma de todas as antecipações)
- E111 PA020008: R$ 2.749,50 (ESPECIAL, acumulado dos dois passes)
- E116 inseridos: 5

---

## Achados dos arquivos modelo reais

### SPED real (SPED_FISCAL_CNPJ_22486965000179_..._04_2026)
- 63.919 C100: 695 ENTRADA + 63.224 SAÍDA (NFC-e)
- 147 participantes no mapa (0150)
- E110 VL_DEB_ESP já = R$ 6.571,15 (antecipações já lançadas manualmente)
- E111 PA020008 já = R$ 3.686,79
- Quando testado com `Detalhamento 1152 FG.xls`, o dedup detectou que os **4 C197 PA70000008 já existiam** nos blocos C100 correspondentes — nenhuma reinserção foi feita (comportamento correto)

### Planilhas reais
- `Detalhamento 1152 FG.xls`: nome diz "1152" mas **conteúdo tem COD1173** → parser lê o título, não o nome do arquivo
- `Detalhamento 1173 FG.xls`: 1 NF, R$ 1.024,10, Formato B (SERIE / NOTA = "1/27146")

---

## Próximos passos (Fase 2)

Ver [[phase2-api-tasks]] (a criar).

1. Wired Celery task `process_sped_job` ao motor (atualmente stub com NotImplementedError)
2. Endpoints de upload para S3
3. Polling de status no frontend
4. Validação manual no Validador SPED com um arquivo SPED "cru" (sem antecipações pré-lançadas)
