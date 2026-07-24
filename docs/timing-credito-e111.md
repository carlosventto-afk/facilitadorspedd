# Timing do crédito E111 (antecipado especial)

Status: **implementado e em produção**, com ressalva — ver seção final.
Data: 2026-07-21 | Commit: `aa4934c` | Testes: 95/95 passando

---

## O problema

O Validador SPED (PVA) acusava, só em cenários **devedores**: *"O valor da
soma dos registros E116 deve ser igual à soma dos campos VL_ICMS_RECOLHER e
DEB_ESP do registro E110"*.

Causa raiz: o motor lançava o débito especial (C197/E116/DEB_ESP) e o
crédito correspondente (E111) no **mesmo mês**. A orientação oficial da
SEFA-PA diz que não é assim.

## A regra oficial (SEFA-PA, Orientação 1173)

Arquivo `Legislação/Orientao-de-Escriturao-do-Antecipado-Especial---1173.pdf`
(2 páginas, sempre esteve no repositório).

> **§1(d)** — o registro E116 (obrigação/vencimento) tem prazo de
> recolhimento até o 10º dia do **segundo** mês subsequente à entrada da
> mercadoria em território paraense.

> **§2** — *"A apropriação do crédito do imposto antecipado especial será
> feita na EFD, no mês subsequente ao da entrada em território paraense
> [...]. Estes valores são equivalentes aos valores do ICMS antecipado
> especial lançado como Débito Especial na EFD anterior."*

Resumindo: débito (C197/E116/DEB_ESP) no mês N; crédito (E111, campo 8 do
E110) no mês **N+1**, em EFDs separados.

## O que foi implementado

Como o motor processa **um período por job**, sem nenhum estado entre
execuções, foi criado um livro-razão de crédito pendente:

- Tabela `pending_antecipacao_credits` (`company_id`, `competencia_origem`,
  `valor`, `status` PENDING/CLAIMED, `source_job_id`, `claimed_in_job_id`).
- Job do mês N: lança o débito normalmente, mas o crédito ESPECIAL apurado
  (`ProcessingResult.especial_total`) vira um registro PENDING — não é
  lançado no arquivo desse mês.
- Próximo job processado dessa empresa (não precisa ser exatamente o mês
  civil seguinte — cobre meses pulados): soma todo crédito PENDING com
  `competencia_origem` anterior, lança como E111, marca CLAIMED.
- Reprocessamento do job de origem depois do crédito já ter sido
  reivindicado: se o valor recalculado bater, nada muda; se divergir, o
  registro já reivindicado **não é sobrescrito silenciosamente** — só gera
  um aviso (`JobLog` nível WARN) pedindo revisão manual, porque o EFD que já
  usou aquele valor pode já ter sido transmitido à SEFA.
- Visibilidade: `GET /firms/me/companies/{id}/pending-credits` lista os
  créditos PENDING e CLAIMED de uma empresa (só a API por enquanto, sem tela
  no frontend ainda).

Código: `backend/app/sped/writer.py` (`SpedEnricher.enrich`, parâmetro
`credit_to_claim`), `backend/app/workers/tasks.py`
(`run_sped_processing`), migration `backend/alembic/versions/0004_*.py`.

## ⚠️ O que precisa de validação real de um contador

O mecanismo em si (débito num mês, crédito no seguinte, com livro-razão
entre jobs) segue a regra oficial acima à risca. Mas 3 comportamentos em
casos extremos, que a orientação da SEFA-PA **não especifica**, foram
decididos por simulação — o Claude respondendo "o que um contador
provavelmente diria", sem confirmação real. O usuário decidiu seguir com a
implementação mesmo assim, ciente do risco.

1. **Empresa pula um mês de processamento** (ex.: processa Janeiro, não
   processa Fevereiro, processa Março) — **o crédito de Janeiro expira, ou
   ainda pode ser reivindicado em Março?**
   Implementado como: **não expira**, é reivindicado no próximo período
   processado, seja qual for. Raciocínio usado: crédito de ICMS
   não-cumulativo geralmente pode ser aproveitado dentro do prazo
   decadencial de 5 anos (LC 87/96, art. 23) — mas isso é inferência geral,
   não algo que a Orientação 1173 confirme para este regime específico.

2. **Job de origem do crédito é reprocessado depois do crédito já ter sido
   reivindicado**, com um valor recalculado diferente — **o que fazer com
   a divergência?**
   Implementado como: não sobrescreve automaticamente, só avisa via log
   para revisão manual. Essa é mais uma decisão de integridade de dados do
   que fiscal, risco menor que o item 1.

3. **Precisa de tela mostrando os créditos pendentes, ou pode ficar
   invisível/automático?**
   Implementado com endpoint de leitura (visibilidade), sem UI ainda. Risco
   baixo — só afeta conveniência, não o lançamento em si.

**Recomendação**: antes de confiar cegamente nisso para clientes reais,
validar pelo menos o item 1 com um contador que atenda ao regime do
antecipado especial no Pará. Se a resposta real for diferente da premissa
acima, a mudança é localizada — só a consulta em
`backend/app/workers/tasks.py` que busca créditos PENDING antes do
`enrich()`.

## Como verificar

```bash
cd backend && python -m pytest tests/sped/test_writer.py tests/api/test_jobs.py tests/api/test_firms.py -v
```

Testes-chave: `test_credito_especial_e111_reivindicado_no_periodo_seguinte`,
`test_credito_especial_mes_pulado_ainda_e_reivindicado`,
`test_reprocessamento_apos_credito_reivindicado_nao_sobrescreve`
(todos em `backend/tests/api/test_jobs.py`).
