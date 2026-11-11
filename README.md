# Capitu Food

Painel do comedouro da Capitu (Tuya F1 Pro): câmera ao vivo com som, alimentação, agenda, diário de refeições e álbum de fotos automáticas.

## Como as peças se encaixam

| Peça | Onde roda | O que faz |
|---|---|---|
| `docs/` | GitHub Pages | A página. Não contém nenhum segredo. |
| `apps-script/` | Google Apps Script | Recebe os cliques, fala com a Tuya, guarda as fotos no Drive. Tem a chave da Tuya e a senha do painel. |
| `scripts/foto.py` + `.github/workflows/fotos.yml` | GitHub Actions | A cada 5 minutos pergunta ao Apps Script se há foto pendente; se houver, captura um quadro e entrega. |
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

No GitHub: **Settings > Secrets and variables > Actions > New repository secret**:

| Segredo | Valor |
|---|---|
| `APPS_SCRIPT_URL` | O mesmo URL `/exec` |
| `TOKEN_ROBO` | O mesmo valor da propriedade do script |

Para testar na hora: **Actions > Fotos da Capitu > Run workflow**. Os ajustes (ligar, quantos minutos depois da refeição, foto de rotina) ficam no próprio painel, em **Álbum da Capitu**.

## Limites conhecidos

- O horário das fotos é aproximado: o agendador do GitHub atrasa e roda no máximo a cada 5 minutos.
- O GitHub desliga tarefas agendadas de repositórios sem atividade por 60 dias; basta reativar em **Actions**.
- O vídeo vem em 640x360 e depende dos serviços de nuvem da Tuya estarem ativos no projeto.
- A agenda aceita até 10 horários, de 1 a 9 porções, válidos para todos os dias.

## Segurança

- Não coloque a chave da Tuya nem senhas em arquivos do repositório. O `.env` da versão local está no `.gitignore`.
- Cinco senhas erradas seguidas bloqueiam o login por 15 minutos.
- Trocar `SENHA_PAINEL` encerra todas as sessões abertas.
