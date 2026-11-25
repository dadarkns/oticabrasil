# Análise da implementação do banco legado

**Projeto analisado:** Otica Web, em `outputs/otica-web`  
**Base ativa inspecionada:** `data/otica.db` (SQLite)  
**Origem:** conjunto DBF/NTX Clipper incluído no ZIP da ótica  
**Estado do serviço:** fechado durante a análise

## Atualização: integração aplicada

Após a análise inicial, a base SQLite do projeto foi refeita com a cópia principal e a cópia complementar `vDos`. Foram inventariadas 66 tabelas/arquivos DBF, com 29.612 registros físicos, dos quais 1.591 estavam ativos e 28.021 marcados como excluídos. **Somente os 1.591 registros ativos foram levados ao staging**; nenhuma linha excluída foi mantida em `legacy_rows`.

Os dados operacionais de cadastro agora incluem 812 produtos, 6 clientes, 176 fornecedores, 12 vendedores, 6 médicos, 1 loja e 31 formas de pagamento (28 legadas e 3 padrões da aplicação). Vendas novas podem selecionar vendedor por chave estrangeira; a loja importa também o percentual de desconto. A origem foi guardada por tabela (`BASE__...` e `VDOS__...`). Os mestres de produto/fornecedor com códigos coincidentes foram consolidados por chave, privilegiando a cópia principal nas divergências; os registros originais ativos de ambas as fontes continuam consultáveis no arquivo legado. Códigos de cliente duplicados foram preservados em linhas separadas, com sufixo de linha no identificador interno.

O menu **Arquivo legado** permite ao administrador consultar e pesquisar todos os registros ativos arquivados, em modo somente leitura. Segredos com nomes de campo associados a senha/token/chave são mascarados antes do staging. A base passou por `PRAGMA integrity_check` (`ok`), verificação de chaves estrangeiras sem erros, zero linhas excluídas em staging e zero valores legados de senha sem máscara. Os testes automatizados existentes (5 fluxos) e verificações de sintaxe Python/JavaScript passaram.

**Limite importante:** “100%” nesta etapa significa 100% dos registros ativos encontrados nas duas cópias disponíveis, preservados no arquivo legado, e cadastros mestres aplicáveis carregados no modelo operacional. Os 11 registros ativos de `NFS`, 16 de `NFSC`, 21 de `NFRECEB`, 13 de `CAIXA`, 27 de `CONTAS` e 16 de `FINANPG` da cópia `vDos` ainda não foram convertidos em lançamentos contábeis normalizados. Eles estão íntegros e pesquisáveis no arquivo legado, sem alterar contas ou saldos ativos. A conversão financeira precisa de validação das regras e vínculos para evitar duplicar ou distorcer saldos.

## Conclusão executiva

A implementação atual é uma **migração integral de retenção dos registros ativos disponíveis**, mais importação operacional dos cadastros, mas ainda não é uma conversão financeira normalizada completa.

- O importador reconhece as 33 DBFs da cópia principal e 33 da cópia `vDos`: 29.612 registros físicos somados. Os 1.591 ativos estão no arquivo legado; as 28.021 linhas marcadas como excluídas foram omitidas.
- Cadastros operacionais têm mapeamento de produtos, clientes, fornecedores, vendedores, médicos, lojas e formas de pagamento. Todos os demais campos e registros ativos permanecem no arquivo legado pesquisável.
- As tabelas normalizadas de transações do sistema novo continuam sem histórico importado. A cópia `vDos` contém registros financeiros e de vendas ativos, agora preservados no arquivo legado; precisam ser normalizados e conciliados antes de operar como saldos atuais.
- A aplicação pode iniciar e operar fluxos novos de venda/compra/estoque/recebimento em seu próprio modelo, mas eles não são uma continuação dos registros históricos do Clipper.
- A preservação de todo o dado em JSON decodificado não preserva byte a byte o DBF, índices NTX, arquivos de memo ou semântica dos programas. Os arquivos de origem devem continuar arquivados como referência.

**Parecer:** a base está íntegra para desenvolvimento/homologação e retém todos os registros ativos das duas cópias encontradas. Não usar os saldos do novo financeiro como histórico oficial até a normalização e reconciliação dos movimentos legados e confirmação de que essas cópias são as fontes completas de produção.

## Inventário quantitativo da cópia principal (`BASE`)

| Tabela | Registros | Ativos | Marcados excluídos | Tratamento após integração |
|---|---:|---:|---:|---|
| AGENDA | 1 | 1 | 0 | Apenas staging |
| ARQ01 | 11 | 6 | 5 | Arquivo legado ativo; campos de credencial mascarados |
| BAIXAS | 0 | 0 | 0 | Apenas staging |
| BAIXAS1 | 0 | 0 | 0 | Apenas staging |
| CAIXA | 0 | 0 | 0 | Apenas staging |
| CHEQUE | 0 | 0 | 0 | Apenas staging |
| CLASSE | 0 | 0 | 0 | Apenas staging |
| CLIENTES | 0 | 0 | 0 | Mapeamento existe; nenhum registro ativo para carregar |
| CONTAS | 0 | 0 | 0 | Apenas staging |
| DESPESA | 0 | 0 | 0 | Apenas staging |
| ENTRADA | 8 | 0 | 8 | Apenas staging; registros marcados excluídos |
| ENTRADAE | 0 | 0 | 0 | Apenas staging |
| ENTRADAL | 0 | 0 | 0 | Apenas staging |
| ESTOQUE | 0 | 0 | 0 | Apenas staging |
| FINANPG | 0 | 0 | 0 | Apenas staging |
| FORNECED | 294 | 160 | 134 | Mapeado para fornecedores ativos |
| ITENS | 0 | 0 | 0 | Apenas staging |
| LENTES | 0 | 0 | 0 | Mapeamento existe; nenhum registro ativo para carregar |
| LOJA | 20 | 1 | 19 | Mapeado para lojas ativas; alguns campos omitidos |
| MECANICO | 0 | 0 | 0 | Apenas staging |
| MEDICO | 18 | 6 | 12 | Mapeado para médicos ativos |
| NFPAGAR | 0 | 0 | 0 | Apenas staging |
| NFRECEB | 0 | 0 | 0 | Apenas staging |
| NFS | 0 | 0 | 0 | Apenas staging |
| NFSC | 0 | 0 | 0 | Apenas staging |
| PRODACAB | 0 | 0 | 0 | Apenas staging |
| PRODUCAO | 0 | 0 | 0 | Apenas staging |
| PRODUTOS | 13.981 | 810 | 13.171 | Mapeado para produtos ativos |
| SAIDA | 0 | 0 | 0 | Apenas staging |
| SAIDAE | 0 | 0 | 0 | Apenas staging |
| SAIDAL | 0 | 0 | 0 | Apenas staging |
| TIPO | 29 | 28 | 1 | Mapeado para formas de pagamento ativas |
| VENDEDOR | 70 | 8 | 62 | 8 vendedores carregados no cadastro operacional |
| **Total** | **14.432** | **1.020** | **13.412** | **33 fontes da cópia principal** |

Os números acima descrevem apenas a cópia principal. O snapshot SQLite atual tem 66 fontes e 1.591 linhas ativas em `legacy_rows`; a cópia `vDos` contribui com clientes e movimentos. Contagens operacionais atuais: 812 produtos, 6 clientes, 176 fornecedores, 12 vendedores, 6 médicos, 1 loja e 31 formas de pagamento. As tabelas de movimentos normalizadas continuam sem histórico importado.

## O que está implementado

### Persistência e importação

- O esquema de aplicação contempla usuários, clientes, fornecedores, médicos, lojas, formas de pagamento, produtos, vendas/itens, receitas, ordens de laboratório, contas a receber, compras/itens, contas a pagar, caixa, estoque e trilha de auditoria.
- O importador consegue ler os DBFs, decodifica texto como CP850 e armazena registros ativos em `legacy_rows`, com fonte e número da linha. Itens excluídos são contabilizados mas omitidos.
- Registros marcados excluídos não entram nos cadastros operacionais, o que evita reativação automática de cadastros antigos.
- Chaves legadas são guardadas em alguns cadastros para facilitar rastreio e atualizações idempotentes.
- O aplicativo usa PostgreSQL como opção de implantação e SQLite no modo local atual. A base SQLite presente é a que contém a importação examinada; o PostgreSQL não foi validado como contendo esta mesma carga.

### Cobertura dos mapeamentos ativos

| Origem | Destino atual | Cobertura/observação |
|---|---|---|
| PRODUTOS | `products` | Carrega 812 produtos após reconciliação por código entre as cópias; a cópia principal prevalece nas divergências. Código, descrição, marca/modelo, unidade, cor/tamanho, tipo, estoque, mínimo, custo e preço. Campos comerciais e de rastreio seguem no arquivo legado. |
| LENTES | `products` | Mapeamento escrito, mas não há linhas ativas nesta cópia. |
| CLIENTES | `customers` | 6 clientes ativos da cópia `vDos`; códigos repetidos preservados separadamente. A cópia principal não contém clientes ativos. |
| FORNECED | `suppliers` | 176 fornecedores após reconciliar as duas cópias; mantém os campos mapeados e arquiva todos os campos de origem. |
| MEDICO | `doctors` | 6 médicos após reconciliar duas fontes coincidentes. |
| LOJA | `stores` | 1 loja após reconciliar duas fontes coincidentes; `PERCDESC` requer mapeamento semântico para `discount_percent`. |
| TIPO | `payment_methods` | 28 formas legadas ativas mais 3 padrões atuais da aplicação. |
| VENDEDOR | `sellers` | 12 vendedores ativos das duas cópias; vendas históricas ainda não ligadas a esta entidade. |
| ARQ01 | Arquivo legado | Usuários antigos permanecem consultáveis sem segredo; não são contas de login na aplicação nova. |

## Lacunas de preservação e uso

1. **Movimentos e histórico:** os registros ativos de vendas (`NFS`/`NFSC`), baixas/recebimentos, caixa, contas e financeiro da cópia `vDos` estão preservados e pesquisáveis no arquivo legado, mas ainda não foram convertidos para vendas/itens/baixas/caixa/contas normalizados. Não alteram os saldos operacionais atuais.
2. **Dados de receita:** o legado contém mais campos oftálmicos do que o destino atual. O modelo atual cobre médico, descrição/tipo de lente, adição, esfera/cilindro/eixo/DNP/altura e valores de perto de forma parcial; faltam ou não estão representados diversos campos de longe/perto, como distâncias pupilares, prismas/CO e medidas por olho. Requer matriz campo a campo e validação com optometrista/operador.
3. **Chaves e relacionamentos:** identificadores e vínculos embutidos em tabelas largas/denormalizadas ainda não foram reconciliados com chaves estrangeiras no modelo novo. Importar movimentos antes dos cadastros e da regra de correspondência pode associar venda, cliente, vendedor, loja, produto ou médico incorretamente.
4. **Índices:** os arquivos NTX não são importados. Índices devem ser entendidos como pistas de ordenação/busca e recriados no banco novo após identificar as chaves e regras de negócio; não se deve migrar os arquivos NTX como índices ativos.
5. **Fidelidade técnica:** staging armazena valores JSON após decodificação, não os bytes originais dos registros. Campos numéricos decimais ficam textuais no arquivo legado para evitar arredondamento binário na etapa de leitura. Os DBFs originais seguem necessários para auditoria e reprocessamento; campos numéricos do modelo operacional ainda precisam de validação de precisão e totais.
6. **Exclusões e auditoria:** sinalizadores e linhas excluídas são mantidos em staging, mas não há uma interface de revisão que explique exclusões, nem trilha da origem/transformação por campo nos registros canônicos.
7. **Ambiguidade do pacote:** ZIP contém fontes, utilitários e arquivos que podem pertencer a outros programas ou rotinas. A lista da cópia DBF é um recorte físico, não um catálogo aprovado de funcionalidades.

## Segurança de credenciais

O importador agora mascara campos com nomes associados a senha, token ou chave antes de inserir os valores no staging. A carga SQLite foi verificada: nenhum registro excluído está no staging e nenhum valor do campo de credencial legado aparece sem máscara. Os dados originais permanecem no ZIP de origem, que deve continuar restrito; o ZIP novo do sistema contém a carga sanitizada e dados pessoais de negócio, então também deve ser compartilhado somente com pessoas autorizadas.

## Plano técnico recomendado

### P0 — proteger a cópia já migrada

- **Concluído:** o importador mascara campos de senha/token/chave antes do staging; exclui os registros marcados como excluídos; a base foi refeita, validada e compactada com limpeza segura.
- **Concluído:** o novo ZIP do projeto foi recriado a partir da base saneada; o ZIP original de entrada permaneceu intacto.
- Restringir o compartilhamento do arquivo do projeto e da base local, pois contêm dados pessoais de clientes e movimentações.
- Confirmar a origem da base e obter uma cópia integral aprovada antes de chamar isso de migração completa.

### P1 — fechar modelo e dicionário de dados

- Produzir mapeamento formal de todos os campos de cada DBF e regras de chave, incluindo campos não mapeados, códigos, flags, decimais, datas e exclusões.
- Adicionar cadastro de vendedores e ligar venda ao vendedor por chave; decidir se usuários do sistema e vendedores são entidades distintas.
- Mapear `LOJA.PERCDESC`, revisar campos de fornecedor e preservar campos sem destino em estrutura de legado consultável ou campos próprios.
- Validar codificação, identificadores duplicados, códigos vazios, colisões de chave e domínio dos códigos de produto/tipo.

### P2 — recuperar o histórico e a operação óptica

- Expandir a receita para os campos oftálmicos originais e validar impressão e acompanhamento de laboratório.
- Implementar a migração de vendas, itens, pagamentos/baixas, caixa, contas, compras e movimentos quando a base de produção confirmar que há dados.
- Definir tratamento de cancelamentos, parcelas, recebimentos parciais, cheques, devoluções, saldo de estoque e datas históricas; conferir total por período e entidade.
- Priorizar relatórios legados efetivamente usados, incluindo extratos, contas vencidas, venda por vendedor, caixa e estoque.

### P3 — ensaio, reconciliação e virada

- Recriar índices necessários como índices PostgreSQL/SQLite conforme o ambiente oficial.
- Executar importação repetível em homologação, mantendo origem somente leitura.
- Comparar contagens, chaves, saldos, totais financeiros e amostras campo a campo; registrar toda diferença com causa e aprovação do responsável.
- Testar restauração de backup, concorrência, permissões, impressão e trilha de auditoria antes da virada.

## Critérios para considerar a migração concluída

- Cada tabela de origem tem destino definido: migrada, arquivada para consulta, descartada com justificativa ou aguardando fonte completa.
- Relatório de auditoria contém quantidade física/ativa/excluída, erros, nulos, duplicidades e totais antes/depois.
- Todos os cadastros necessários têm chaves legadas estáveis e relacionamentos validados.
- Movimentos financeiros e estoque conciliam com relatórios do legado para períodos de amostra e para o total histórico disponível.
- Receita e laboratório preservam todos os campos confirmados como usados.
- Segredos não aparecem no staging, logs, exportações ou ZIP distribuível; backup e restauração foram demonstrados.
- Responsáveis da ótica aprovam os fluxos de trabalho e as diferenças documentadas.

## Referências no projeto

- Importador DBF e mapeamentos: `tools/dbf_import.py`
- Esquema SQLite, autenticação e entidades: `server.py`
- Esquema PostgreSQL: `migrations/001_initial_postgres.sql`
- Como executar e limitações atuais: `README.md`
