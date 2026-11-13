# Capitu Food

Painel do comedouro da Capitu (Tuya F1 Pro): câmera ao vivo com som, alimentação, agenda, diário de refeições e álbum de fotos automáticas.

## Como as peças se encaixam

| Peça | Onde roda | O que faz |
|---|---|---|
| `docs/` | GitHub Pages | A página, com favicon e ícone da tela inicial (gerados por `scripts/gerar_icones.py` a partir do logo). Não contém nenhum segredo. |
| `apps-script/` | Google Apps Script | Recebe os cliques, fala com a Tuya, guarda as fotos no Drive. Tem a chave da Tuya e a senha do painel. |
| `scripts/foto.py` + `.github/workflows/fotos.yml` | GitHub Actions | Chamado pelo Apps Script quando há foto devida (e, como reserva, a cada 15 minutos): captura um quadro e entrega. |
| `servidor.py`, `tuya.py`, `painel.html` | Seu computador | Versão local, opcional. Usa o arquivo `.env`. |

## Publicar

### 1. Apps Script

1. Em <https://script.google.com>, crie um projeto novo.
2. Cole o conteúdo de `apps-script/Code.gs` no arquivo `Código.gs`.
3. Em **Configurações do projeto**, marque **Mostrar o arquivo de manifesto "appsscript.json"** e cole o conteúdo de `apps-script/appsscript.json`.
4. Ainda em **Configurações do projeto > Propriedades do script**, crie:

   | Propriedade | Valor |
   |---|---|
   | `TUYA_ACCESS_ID` | Access ID do projeto na Tuya |
   | `TUYA_ACCESS_SECRET` | Access Secret do projeto na Tuya |
   | `TUYA_DEVICE_ID` | ID do comedouro |
   | `SENHA_PAINEL` | A senha que a página vai pedir |
   | `TOKEN_ROBO` | Uma senha longa e aleatória, só para o GitHub Actions |

5. No editor, escolha a função `testarConfiguracao` e clique em **Executar**. Autorize o acesso quando o Google pedir. O registro deve mostrar o nome do comedouro e a pasta das fotos.
6. **Implantar > Nova implantação > App da Web**: executar como **Eu**, acesso **Qualquer pessoa**. Copie o URL que termina em `/exec`.

Ao mudar o código depois, use **Implantar > Gerenciar implantações > Editar > Nova versão**, para o URL continuar o mesmo.

### 2. Página

1. Edite `docs/config.js` e cole o URL `/exec` entre as aspas.
2. Envie a alteração para o branch `main`. A tarefa **Publicar a página** copia `docs/` para o branch `gh-pages`, de onde o GitHub Pages serve o site em <https://lffzdsf.github.io/capitufood/>.
3. Se o site não aparecer, confira em **Settings > Pages** se a origem é **Deploy from a branch**, branch `gh-pages`, pasta `/ (root)`.

### 3. Fotos automáticas

O GitHub sozinho atrasa ou pula tarefas agendadas (chegou a rodar 4 vezes por dia em vez de 288). Por isso o Google, que é pontual, confere a cada 5 minutos se há foto devida e chama o robô do GitHub na hora.

**a) Segredos do repositório** (**Settings > Secrets and variables > Actions > New repository secret**):

| Segredo | Valor |
|---|---|
| `APPS_SCRIPT_URL` | O URL `/exec` do Apps Script |
| `TOKEN_ROBO` | O mesmo valor da propriedade do script |

**b) Token para o Google chamar o GitHub** (**Settings > Developer settings > Personal access tokens > Fine-grained tokens > Generate new token**):

- **Repository access:** *Only select repositories* e escolha `capitufood`.
- **Permissions > Repository permissions > Actions:** *Read and write*.
- Copie o token e crie no Apps Script a propriedade `GITHUB_TOKEN`.

**c) Ligar o agendador:** depois de colar o `Code.gs` novo e o `appsscript.json` novo, rode a função `instalarGatilho` no editor (autorize de novo quando o Google pedir). Em seguida, **Implantar > Gerenciar implantações > Editar > Nova versão**.

Para testar: **Actions > Fotos da Capitu > Run workflow**. Os ajustes (ligar, minutos depois da refeição, foto de rotina) ficam no painel, em **Álbum da Capitu**, que também mostra o estado do agendador e avisos de erro.

## Limites conhecidos

- O horário das fotos é aproximado: o Google confere a cada 5 minutos e o robô leva cerca de um minuto para iniciar.
- O token do GitHub vence (no máximo em 1 ano). Quando vencer, o álbum avisa "token inválido ou vencido"; gere outro e troque a propriedade `GITHUB_TOKEN`.
- O GitHub desliga tarefas agendadas de repositórios sem atividade por 60 dias; basta reativar em **Actions**.
- O vídeo vem em 640x360 e depende dos serviços de nuvem da Tuya estarem ativos no projeto.
- A agenda aceita até 10 horários, de 1 a 9 porções, válidos para todos os dias.

## Segurança

- Não coloque a chave da Tuya nem senhas em arquivos do repositório. O `.env` da versão local está no `.gitignore`.
- Cinco senhas erradas seguidas bloqueiam o login por 15 minutos.
- Trocar `SENHA_PAINEL` encerra todas as sessões abertas.
