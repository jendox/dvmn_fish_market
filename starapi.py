import logging
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO

from httpx import AsyncClient

logger = logging.getLogger("starapi")


class StarapiException(Exception): ...


class ProductNotFound(StarapiException): ...


class CartNotFound(StarapiException): ...


class CustomerNotFound(StarapiException): ...


@dataclass
class Product:
    id: int
    document_id: str
    title: str
    description: str
    price: Decimal
    picture_url: str | None = None


@dataclass
class CartItem:
    document_id: str
    title: str
    amount: float
    price: Decimal | None = None


@dataclass
class Customer:
    telegram_id: int
    telegram_username: str
    email: str


async def get_products(client: AsyncClient) -> list[Product]:
    try:
        response = await client.get("/api/products")
        response.raise_for_status()
        products = response.json().get("data", [])
        return [
            Product(
                id=product["id"],
                document_id=product["documentId"],
                title=product["title"],
                description=product["description"],
                price=Decimal(product["price"]),
            )
            for product in products
        ]
    except Exception as exc:
        logger.error(f"Ошибка получения списка продуктов: {str(exc)}")
        return []


async def get_product(document_id: str, client: AsyncClient) -> Product:
    try:
        response = await client.get(f"/api/products/{document_id}?populate[picture][fields][0]=url")
        response.raise_for_status()
        product = response.json().get("data")
        if not product:
            logger.warning(f"Продукт document_id={document_id} не найден")
            raise ProductNotFound(f"Продукт id={document_id} не найден.")

        picture_url = None
        if picture := product.get("picture"):
            picture_url = picture[0].get("url")

        return Product(
            id=product["id"],
            document_id=product["documentId"],
            title=product["title"],
            description=product["description"],
            price=Decimal(product["price"]),
            picture_url=picture_url,
        )
    except Exception as exc:
        logger.error(f"Ошибка получения информации о продукте: {str(exc)}")
        raise


async def download_image(image_url: str, client: AsyncClient) -> BytesIO:
    response = await client.get(image_url)
    response.raise_for_status()
    return BytesIO(response.content)


async def get_cart_by_telegram_id(telegram_id: int, client: AsyncClient) -> str:
    try:
        params = {"filters[telegram_id][$eq]": telegram_id}
        response = await client.get("/api/carts", params=params)
        response.raise_for_status()
        carts = response.json().get("data")
        if not carts:
            raise CartNotFound(f"Корзина для telegram_id={telegram_id} не найдена.")
        return carts[0]["documentId"]
    except Exception as exc:
        logger.error(f"Ошибка поиска корзины для telegram_id={telegram_id}: {str(exc)}")
        raise


async def create_cart(telegram_id: int, client: AsyncClient) -> str:
    try:
        payload = {"data": {"telegram_id": str(telegram_id)}}
        response = await client.post("/api/carts", json=payload)
        response.raise_for_status()
        new_cart = response.json()
        cart_doc_id = new_cart["documentId"]
        logger.info(f"Создана корзина {cart_doc_id} для пользователя telegram_id={telegram_id}")
        return cart_doc_id
    except Exception as exc:
        logger.error(f"Ошибка создания корзины для пользователя {telegram_id}: {str(exc)}")
        raise


async def ensure_cart(telegram_id: int, client: AsyncClient) -> str:
    try:
        return await get_cart_by_telegram_id(telegram_id, client)
    except CartNotFound:
        return await create_cart(telegram_id, client)
    except Exception as exc:
        logger.error(f"Неожиданная ошибка: {str(exc)}")
        raise


async def add_product_to_cart(
    telegram_id: int,
    product_doc_id: str,
    amount: float,
    client: AsyncClient,
) -> None:
    try:
        cart_doc_id = await ensure_cart(telegram_id, client)
        payload = {
            "data": {
                "amount": amount,
                "cart": cart_doc_id,
                "product": product_doc_id,
            },
        }
        response = await client.post("/api/cart-items", json=payload)
        response.raise_for_status()
        logger.info(
            f"Добавлен product_id={product_doc_id} amount={amount} в cart={cart_doc_id} (telegram_id={telegram_id})",
        )
    except Exception as exc:
        logger.error(f"Ошибка добавления товара {product_doc_id} в корзину пользователя {telegram_id}: {str(exc)}")
        raise


async def get_cart_items(telegram_id: int, client: AsyncClient) -> list[CartItem]:
    try:
        params = {
            "filters[telegram_id][$eq]": telegram_id,
            "populate[cart_items][populate]": "product",
        }
        response = await client.get("/api/carts", params=params)
        response.raise_for_status()
        carts = response.json().get("data", [])
        if not carts:
            return carts

        cart = carts[0]
        raw_items = cart.get("cart_items", [])
        items: list[CartItem] = []
        for item in raw_items:
            item_id = item["documentId"]
            product = item.get("product", {})
            title = product.get("title", "Без названия")
            price_raw = product.get("price")
            price = Decimal(str(price_raw)) if price_raw is not None else None
            amount = float(item.get("amount", 0))
            items.append(
                CartItem(
                    document_id=item_id,
                    title=title,
                    amount=amount,
                    price=price,
                ),
            )
        return items
    except Exception as exc:
        logger.error(f"Ошибка получения корзины для telegram_id={telegram_id}: {str(exc)}")
        raise


async def delete_cart_item(cart_item_doc_id: str, client: AsyncClient) -> None:
    try:
        response = await client.delete(f"/api/cart-items/{cart_item_doc_id}")
        response.raise_for_status()
    except Exception as exc:
        logger.error(f"Ошибка удаления CartItem documentId={cart_item_doc_id}: {str(exc)}")
        raise


async def add_customer(
    customer: Customer,
    client: AsyncClient,
) -> None:
    payload = {
        "data": {
            "telegram_id": customer.telegram_id,
            "email": customer.email,
            "telegram_username": customer.telegram_username,
        },
    }
    try:
        await client.post("/api/customers", json=payload)
    except Exception as exc:
        logger.error(
            f"Ошибка создания клиента email={customer.email} telegram_id={customer.telegram_id}: {str(exc)}",
        )


async def get_customer_by_telegram_id(telegram_id: int, client: AsyncClient) -> Customer:
    try:
        params = {"filters[telegram_id][$eq]": telegram_id}
        response = await client.get("/api/customers", params=params)
        response.raise_for_status()
        customers = response.json().get("data")
        if not customers:
            raise CustomerNotFound(f"Клиент с telegram_id={telegram_id} не найден.")
        return Customer(
            telegram_id=customers[0]["telegram_id"],
            telegram_username=customers[0]["telegram_username"],
            email=customers[0]["email"],
        )
    except Exception as exc:
        logger.error(f"Ошибка поиска клиента с telegram_id={telegram_id}: {str(exc)}")
        raise
