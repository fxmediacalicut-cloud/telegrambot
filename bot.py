import logging
import os
import json
import qrcode
from io import BytesIO
from datetime import datetime
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, ConversationHandler, filters
)

# ------------------- LOGGING -------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

# ------------------- BOT CONFIG -------------------
TOKEN = os.getenv("BOT_TOKEN", "8244380773:AAGZE3T74x-IYHxDqJFja_j4vaGdpsni4Kk")
ADMIN_ID = int(os.getenv("ADMIN_ID", "564401901"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://telegrambot-production-ee51.up.railway.app")

PRODUCTS_FILE = "products.json"
INITIAL_PRODUCTS = {
    "p1": {"name": "Product A", "price": 100, "access": "🔑 Access: https://google.com/a", "image": None},
    "p2": {"name": "Product B", "price": 200, "access": "🔑 Access: https://example.com/b", "image": None},
    "p3": {"name": "Product C", "price": 300, "access": "🔑 Access: https://example.com/c", "image": None},
}

UPI_ID = "800846077@bharatpe"

# ------------------- LOAD / SAVE PRODUCTS -------------------
def load_products():
    if os.path.exists(PRODUCTS_FILE):
        try:
            with open(PRODUCTS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logging.error("Failed to load products.json: %s", e)
    with open(PRODUCTS_FILE, "w") as f:
        json.dump(INITIAL_PRODUCTS, f, indent=2)
    return dict(INITIAL_PRODUCTS)

def save_products(products):
    try:
        with open(PRODUCTS_FILE, "w") as f:
            json.dump(products, f, indent=2)
    except Exception as e:
        logging.error("Failed to save products.json: %s", e)

PRODUCTS = load_products()
user_product = {}
pending_txns = {}
awaiting_reasons = {}

# ------------------- BOT HANDLERS -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PRODUCTS:
        await update.message.reply_text("⚠️ No products available right now.")
        return
    keyboard = [[InlineKeyboardButton(f"{p['name']} – ₹{p['price']}", callback_data=key)] for key, p in PRODUCTS.items()]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👋 Welcome! Choose a product:", reply_markup=reply_markup)

async def product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_code = query.data
    user_id = query.from_user.id
    user_product[user_id] = product_code
    product = PRODUCTS[product_code]

    amount = product['price']
    upi_url = f"upi://pay?pa=BHARATPE.8000846077@fbpe&pn=VIDEO EDITORS IN KERALA&am={amount}&cu=INR"
    qr_img = qrcode.make(upi_url)
    bio = BytesIO()
    bio.name = 'upi_qr.png'
    qr_img.save(bio, 'PNG')
    bio.seek(0)

    caption_text = (
        f"🛒 You selected: {product['name']} (₹{amount})\n\n"
        f"💳 UPI ID: `{UPI_ID}`\n"
        f"📌 Copy this UPI link:\n`{upi_url}`\n\n"
        "📌 Or scan the QR above.\n\n"
        "👉 After payment, upload your payment screenshot here."
    )

    await query.message.reply_photo(photo=bio, caption=caption_text, parse_mode="Markdown")

async def payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "NoUsername"
    if user_id not in user_product:
        await update.message.reply_text("⚠️ Please select a product first using /start.")
        return
    product_code = user_product[user_id]
    product = PRODUCTS[product_code]

    photo = update.message.photo[-1]
    file = await photo.get_file()
    os.makedirs("screenshots", exist_ok=True)
    filename = f"screenshots/{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
    await file.download_to_drive(filename)

    txn_id = os.path.basename(filename)
    pending_txns[txn_id] = {"user_id": user_id, "username": username, "product_code": product_code, "file": filename}

    with open("transactions.txt", "a") as f:
        f.write(f"UserID: {user_id}, Username: @{username}, Product: {product['name']}, Screenshot: {txn_id}, Status: PENDING\n")

    await update.message.reply_text(f"✅ Screenshot received for {product['name']}. Await verification.")

    approve_reject_btns = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve & Send Access", callback_data=f"approve_{txn_id}"),
         InlineKeyboardButton("❌ Reject Payment", callback_data=f"reject_{txn_id}")]
    ])
    with open(filename, "rb") as photo_file:
        await context.bot.send_photo(
            ADMIN_ID, photo=photo_file,
            caption=f"⚠️ New Payment Pending\n\nUser: @{username}\nProduct: {product['name']}\nScreenshot ID: {txn_id}",
            reply_markup=approve_reject_btns
        )

async def approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return
    txn_id = query.data.replace("approve_", "")
    if txn_id not in pending_txns:
        await query.message.reply_text("❌ Transaction not found.")
        return
    data = pending_txns.pop(txn_id)
    buyer_id = data["user_id"]
    product = PRODUCTS[data["product_code"]]
    with open("transactions.txt", "a") as f:
        f.write(f"Txn {txn_id} VERIFIED for {buyer_id}, Product: {product['name']}\n")
    await context.bot.send_message(buyer_id, f"🎉 Payment verified!\nHere is your access:\n\n{product['access']}")
    await query.edit_message_caption(caption=f"✅ Approved Txn {txn_id} and access sent to @{data['username']}")

async def reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return
    txn_id = query.data.replace("reject_", "")
    if txn_id not in pending_txns:
        await query.message.reply_text("❌ Transaction not found.")
        return
    awaiting_reasons[ADMIN_ID] = txn_id
    await query.message.reply_text(f"✏️ Type reason for rejecting transaction `{txn_id}`:", parse_mode="Markdown")

async def rejection_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID or ADMIN_ID not in awaiting_reasons:
        return
    txn_id = awaiting_reasons.pop(ADMIN_ID)
    if txn_id not in pending_txns:
        await update.message.reply_text("❌ Transaction not found.")
        return
    reason = update.message.text.strip() or "No reason provided."
    data = pending_txns.pop(txn_id)
    buyer_id = data["user_id"]
    product = PRODUCTS[data["product_code"]]
    with open("transactions.txt", "a") as f:
        f.write(f"Txn {txn_id} REJECTED for {buyer_id}, Reason: {reason}\n")
    await context.bot.send_message(
        buyer_id,
        f"🚫 *Payment Rejected*\n\n❌ Your payment for *{product['name']}* was rejected.\n\n🆔 Screenshot ID: `{txn_id}`\n💬 Reason: {reason}\n\n👉 Please upload a valid screenshot.",
        parse_mode="Markdown"
    )
    await update.message.reply_text(f"✅ Sent rejection reason to buyer of Txn {txn_id}.")

# ------------------- ERROR HANDLER -------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(msg="Exception while handling update:", exc_info=context.error)
    if hasattr(update, 'effective_message') and update.effective_message:
        await update.effective_message.reply_text("⚠️ An error occurred. Please try again later.")

# ------------------- FLASK SERVER -------------------
flask_app = Flask(__name__)
application = Application.builder().token(TOKEN).build()

# Register handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(product_callback, pattern="^p"))
application.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))
application.add_handler(CallbackQueryHandler(reject_callback, pattern="^reject_"))
application.add_handler(MessageHandler(filters.PHOTO, payment_screenshot))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, rejection_reason_handler))
application.add_error_handler(error_handler)

@flask_app.route("/", methods=["GET"])
def index():
    return "Bot is running ✅"

@flask_app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    application.update_queue.put(update)
    return "ok"

if __name__ == "__main__":
    import asyncio
    # Set webhook
    asyncio.run(application.bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}"))
    port = int(os.environ.get("PORT", 8000))
    flask_app.run(host="0.0.0.0", port=port)
