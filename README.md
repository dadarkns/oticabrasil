# Ótica Web

Aplicação web interna para operação de ótica. A interface é responsiva e serve a mesma API que uma futura aplicação nativa de PC poderá consumir.

## Funcionalidades implementadas

- Visão geral com vendas do dia/mês, produtos, clientes, estoque baixo, contas em aberto e fila do laboratório.
- Cadastros de clientes, fornecedores, médicos, lojas, produtos, formas de pagamento e usuários.
- Venda com múltiplos produtos, desconto, cliente, forma de pagamento, parcelas, recebimento inicial e registro da receita oftálmica.
- Criação automática de parcelas a receber, movimentos de estoque e encaminhamento da receita ao laboratório.
- Entrada de compra com atualização de estoque e criação de conta a pagar; ajuste de estoque com motivo e trilha de auditoria.
- Histórico de compras, diário de caixa e lançamentos avulsos de entrada/saída.
- Cancelamento auditado de venda, devolução de itens ao estoque e registro de estorno após confirmação da devolução ao cliente.
- Acompanhamento de laboratório (Pendente, Recebido, Em produção, Pronto, Entregue).
- Baixas parciais ou totais de parcelas e relatório de vendas por período com exportação CSV.
- Login com perfis (Administrador, Gerente, Caixa e Vendas), hash PBKDF2 para senhas e cookie de sessão HttpOnly.
- Banco PostgreSQL para execução com Docker Compose; SQLite local como alternativa imediata para desenvolvimento sem dependências.
- Ferramenta DBF que audita as cópias principal e `vDos`, guarda em staging apenas registros ativos (com credenciais mascaradas) e importa cadastros reconhecidos.

## Execução rápida local (SQLite)

Requer Python 3.10 ou superior. Não requer instalar pacotes Python.

```powershell
$env:ADMIN_PASSWORD = 'defina-uma-senha-com-10-ou-mais-caracteres'
$env:SESSION_SECRET = 'defina-uma-chave-aleatoria-longa'
.\run.ps1
```

Abra `http://127.0.0.1:8000`. Na primeira inicialização, o usuário `admin` é criado usando `ADMIN_PASSWORD`; a aplicação não tem mais uma senha padrão. A senha deve ter ao menos 10 caracteres. Em uma base já inicializada, alterar a variável não troca a senha existente. O produto ainda não tem tela para trocar ou recuperar senhas; essa capacidade deve entrar antes da implantação com usuários finais.

## Execução com PostgreSQL

Instale Docker Desktop, copie `.env.example` para `.env` e troque os três segredos por valores aleatórios exclusivos. Em PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

A aplicação cria as tabelas na primeira inicialização. O Postgres fica no volume Docker `otica_data`; não exponha a porta do banco publicamente. Para implantação em rede, coloque a aplicação atrás de HTTPS e configure `COOKIE_SECURE=1`.

## Auditoria e importação DBF/NTX

A auditoria é somente leitura e não altera arquivos de origem:

```powershell
python tools/dbf_import.py 'C:\caminho\ARQUIVOS OTICA' --include-vdos > auditoria.json
```

O relatório mostra versões, schemas, contagens, registros excluídos e arquivos ilegíveis, sem imprimir os valores pessoais dos registros. Inspecione o resultado e confirme que está apontando para a cópia correta do banco antes de importar.

Para importar, configure `DATABASE_URL` para a base de destino e execute `--import`:

```powershell
$env:DATABASE_URL = 'postgresql://otica:SENHA@localhost:5432/otica'
python tools/dbf_import.py 'C:\caminho\ARQUIVOS OTICA' --include-vdos --import
```

O utilitário guarda os esquemas e os registros ativos de ambas as cópias DBF em `legacy_sources` e `legacy_rows`; registros marcados como excluídos são contabilizados no relatório, mas não são copiados para o banco novo. Campos com aparência de segredo (senha, token, chave) são mascarados. O utilitário mapeia produtos, lentes, clientes, fornecedores, vendedores, médicos, lojas e formas de pagamento para as tabelas atuais, usando o código legado em `legacy_id`. Para incluir uma subpasta `vDos`, passe `--include-vdos`.

### Base importada neste projeto

No workspace de desenvolvimento, `data/otica.db` foi atualizado com as cópias principal e `vDos`: 66 tabelas, 29.612 registros físicos inventariados, 1.591 ativos arquivados e 28.021 excluídos que não foram copiados para o staging. O modelo operacional contém 812 produtos, 6 clientes, 176 fornecedores, 12 vendedores, 6 médicos, 1 loja e 31 formas de pagamento (28 legadas e três padrões). Cadastros repetidos entre as cópias foram reconciliados por código; códigos de cliente repetidos foram mantidos como linhas distintas com identificador legado desambiguado. O histórico ativo de vendas/financeiro está disponível em **Arquivo legado** (consulta somente leitura para administrador) e não altera os saldos do novo financeiro até que seus vínculos sejam validados. Por conter dados pessoais, `data/otica.db` está fora do Git e não é incluído no pacote de código publicado; novas instalações devem reimportar os DBFs autorizados. O Docker Compose usa PostgreSQL separado; para preenchê-lo, extraia os DBFs e execute o comando de importação com `DATABASE_URL` apontando para o PostgreSQL.

**Atenção:** isso é uma primeira conversão técnica, não uma reconciliação contábil aprovada. O conjunto enviado contém tabelas de movimento vazias e outras pertencentes a mais de um domínio. Após importar, confira contagens, campos ambíguos, tabelas duplicadas e totais financeiros com a operação antes de habilitar o novo sistema como fonte oficial. Faça backup do Postgres e guarde os DBF/NTX originais em local controlado.

## API

Base `/api`; autenticação por sessão obtida em `POST /api/login`.

| Recurso | Rotas principais |
|---|---|
| Sessão | `POST /login`, `POST /logout`, `GET /me` |
| Indicadores | `GET /dashboard`, `GET /health` |
| Cadastros | `GET/POST /products`, `/customers`, `/suppliers`, `/doctors`, `/stores`, `/payment-methods`; `GET /sellers` |
| Venda e compra | `GET/POST /sales`, `POST /purchases` |
| Estoque | `POST /stock-adjustments` |
| Laboratório | `GET /lab-orders`, `POST /lab-orders/{id}` |
| Financeiro | `GET /receivables`, `GET /payables`, `GET /cash-movements`, `POST /cash-movements`, `POST /receivables/{id}/payment`, `POST /payables/{id}/payment` |
| Relatório | `GET /reports/sales?from=YYYY-MM-DD&to=YYYY-MM-DD` |
| Usuários | `GET/POST /users` (administrador) |
| Arquivo legado | `GET /legacy/sources`, `GET /legacy/rows?source=ID&q=...` (administrador/gerente, somente leitura) |

`POST /sales/{id}/cancel` permite cancelamento a gerente/administrador. Se já houve recebimento, a primeira chamada retorna `409` e o valor recebido. A segunda chamada só deve enviar `refund_confirmed: true` depois que a devolução ao cliente tiver sido concluída fora do sistema; ela registra o movimento de saída e preserva o histórico da baixa original.

As vendas, compras, baixas, ajustes, cancelamentos e estornos executam suas gravações relacionadas em transação. Exclusão física não é oferecida para preservar histórico. Alterações de cadastros existentes ainda precisam ser adicionadas antes da adoção operacional.

## Verificações

Com Python 3.10+ instalado, rode `python -m unittest discover -s tests -v`. Os testes cobrem venda com receita, vendedor relacionado e parcelas, consulta filtrada do arquivo legado, baixa, compra, ajuste, cancelamento/estorno, permissões de perfil, concorrência de estoque e totais do relatório.

## Próximas etapas para produção

1. Revisar os fluxos e relatórios com usuários da ótica, especialmente compras, cancelamentos, caixa diário, carnês e recebimentos antigos.
2. Completar os mapeamentos de histórico DBF (vendas, baixas, contas, caixa, cheques) a partir da cópia de produção e validar somas e saldos.
3. Adicionar edição/cancelamento auditados, validações de transição de laboratório, segurança CSRF/limitação de tentativas, recuperação de senha e trilha de auditoria consultável.
4. Exercitar a migração em cópia de homologação, comparar contagens e totais, testar restauração do backup e só então planejar a virada.
