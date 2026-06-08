# Bot de tickets profissional para Discord

Versao focada em tickets, sem IA e sem canal de logs.

## Arquivos

- `.env`: somente o token do Discord.
- `main.py`: codigo principal do bot.
- `requirements.txt`: dependencias.
- `bot_tickets.sqlite3`: banco criado automaticamente.
- `transcripts/`: historicos HTML gerados apenas quando staff pedir.

## Como instalar

```bash
pip install -r requirements.txt
python main.py
```

No `.env`, deixe assim:

```env
DISCORD_TOKEN=SEU_TOKEN_AQUI
```

## Intents no Discord Developer Portal

Ative:

- Server Members Intent

O bot nao usa mais IA nem leitura automatica de mensagens, entao nao precisa do Message Content Intent.

## Configuracao principal

Use:

```text
/ticket_config cargo_staff:@Staff categoria_tickets:Tickets
```

Ou:

```text
/configurar cargo_staff:@Staff categoria_tickets:Tickets
```

Esse comando configura apenas:

- cargo staff que vai responder tickets;
- categoria onde os tickets serao criados.

## Painel

Use:

```text
/ticket
```

Vai abrir um modal com:

- titulo;
- mensagem do painel;
- link da imagem PNG.

O link da imagem precisa terminar com `.png`.

## Como o staff e escolhido

Quando alguem abre um ticket, o bot:

1. procura membros online com o cargo staff;
2. evita escolher staff com 2 ou mais tickets abertos;
3. escolhe apenas 1 staff para aquele ticket;
4. deixa o canal privado para o usuario e o staff escolhido.

Se todos ja estiverem ocupados, o bot escolhe quem tiver menos tickets para nao travar o atendimento.

## Regras do ticket

- O botao de fechar aparece para todos.
- Apenas o dono do servidor ou o staff escolhido consegue fechar.
- Nao envia log em nenhum canal.
- Nao envia transcript automatico.
- Transcript so e gerado se o staff usar o botao ou `/ticket_transcript`.

## Comandos

- `/ticket`
- `/ticket_config`
- `/configurar`
- `/ticket_info`
- `/ticket_renomear`
- `/ticket_transcript`
- `/anuncio`
- `/embed`
- `/say`
- `/limpar`
- `/config_ver`
- `/boasvindas_testar`
- `/staff_ping`
- `/ajuda`
- `/status`
