# Telegram Fish Shop Bot (StarAPI + Strapi)

Небольшой учебный проект (Devman): Telegram-бот интернет-магазина рыбы, который работает поверх CMS StarAPI/Strapi.

---

## Требования

- Python **>= 3.13**
- CMS: **StarAPI/Strapi** (локально на `http://localhost:1337` по умолчанию)

---

## Установка

#### Установите uv (если еще не установлен)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Клонируйте репозиторий
```bash
git clone https://github.com/jendox/dvmn_fish_market.git
cd dvmn_fish_market
```

#### Установите зависимости
```bash
uv sync
```

## Настройка

### Получите токен телеграм бота:

Напишите в Telegram [@BotFather](https://telegram.me/BotFather).
Создайте нового бота командой /newbot.
Сохраните полученный токен.

### Установите и настройте CMS Starapi

- Установка [здесь](https://github.com/strapi/strapi?tab=readme-ov-file#-installation).
- Инструкция [здесь](https://docs.strapi.io/cms/intro).

Для работы CMS нужно установить [Node.js](https://nodejs.org/en/).

Запустите CMS локально:
```bash
npm run develop
```
Ожидается, что StarAPI/Strapi крутится локально на `http://localhost:1337`

### Переменные окружения

В корне проекта создайте файл `.env`:
```bash
touch .env
```

Добавьте переменные окружения:
```env
STARAPI_URL=starapi_server_url # по умолчанию используется значение http://localhost:1337
STARAPI_API_TOKEN=your_starapi_token_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_USERNAME=default
REDIS_PASSWORD=your_redis_password
```

## Управление

Бот запускается командой:
```bash
uv run main.py
```

Для завершения работы нажмите `Ctrl+C` в терминале.

## Лицензия

Этот проект лицензирован под MIT License - смотрите файл [LICENSE](LICENSE) для деталей.