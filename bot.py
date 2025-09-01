import logging
import os
import json
import qrcode
from io import BytesIO
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, ConversationHandler, filters
)

# ------------------- LOGGING SETUP -------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

# ------------------- BOT SETUP -------------------
TOKEN = "8244380773:AAGZE3T74x-IYHxDqJFja_j4vaGdpsni4Kk"  # <-- keep your token here
ADMIN_ID = 564401901

PRODUCTS_FILE = "products.json"

# Default initial products (used if products.json doesn't exist)
INITIAL_PRODUCTS = {
    "p1": {"name": "Product A", "price": 100, "access": "🔑 Access: https://google.com/a", "image": None},
    "p2": {"name": "Product B", "price": 200, "access": "🔑 Access: https://example.com/b", "image": None},
    "p3": {"name": "Product C", "price": 300, "access": "🔑 Access: https://example.com/c", "image": None},
}

# Load / Save helpers
def load_products():
    if os.path.exists(PRODUCTS_FILE):
        try:
            with open(PRODUCTS_FILE, "r") as f:
                data = json.load(f)
                # ensure keys and basic structure exist
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logging.error("Failed to load products.json: %s", e)
    # fallback: persist the initial defaults and return them
    with open(PRODUCTS_FILE, "w") as f:
        json.dump(INITIAL_PRODUCTS, f, indent=2)
    return dict(INITIAL_PRODUCTS)

def save_products(products):
    try:
        with open(PRODUCTS_FILE, "w") as f:
            json.dump(products, f, indent=2)
    except Exception as e:
        logging.error("Failed to save products.json: %s", e)

# In-memory structures (keep your existing names)
PRODUCTS = load_products()
user_product = {}       # maps user_id -> last selected product (product code like 'p1')
pending_txns = {}       # maps txn_id (screenshot filename) -> txn details
awaiting_reasons = {}   # admin_id -> txn_id (waiting for rejection reason)

UPI_ID = "800846077@bharatpe"

# ------------------- COMMANDS (unchanged behavior) -------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not PRODUCTS:
        await update.message.reply_text("⚠️ No products available right now.")
        return

    keyboard = [
        [InlineKeyboardButton(f"{p['name']} – ₹{p['price']}", callback_data=key)]
        for key, p in PRODUCTS.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "👋 Welcome to the Payment Bot!\n\nChoose a product:",
        reply_markup=reply_markup
    )

async def product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_code = query.data
    user_id = query.from_user.id
    user_product[user_id] = product_code

    product = PRODUCTS[product_code]

    # Generate QR
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
        f"📌 Copy this UPI link into GPay/PhonePe/Paytm:\n`{upi_url}`\n\n"
        "📌 Or scan the QR above.\n\n"
        "👉 After payment, upload your payment screenshot here."
    )

    await query.message.reply_photo(
        photo=bio, caption=caption_text, parse_mode="Markdown"
    )

# ------------------- PAYMENT SCREENSHOT (unchanged behavior) -------------------
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
    pending_txns[txn_id] = {
        "user_id": user_id, "username": username,
        "product_code": product_code, "file": filename
    }

    with open("transactions.txt", "a") as f:
        f.write(f"UserID: {user_id}, Username: @{username}, Product: {product['name']}, Screenshot: {txn_id}, Status: PENDING\n")

    await update.message.reply_text(
        f"✅ Your screenshot for {product['name']} is received.\nWe will verify and send access shortly."
    )

    approve_reject_btns = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve & Send Access", callback_data=f"approve_{txn_id}"),
            InlineKeyboardButton("❌ Reject Payment", callback_data=f"reject_{txn_id}")
        ]
    ])

    with open(filename, "rb") as photo_file:
        await context.bot.send_photo(
            ADMIN_ID,
            photo=photo_file,
            caption=f"⚠️ New Payment Pending\n\nUser: @{username}\nProduct: {product['name']}\nScreenshot ID: {txn_id}",
            reply_markup=approve_reject_btns
        )

# ------------------- ADMIN ACTIONS (unchanged behavior) -------------------
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

    await context.bot.send_message(
        buyer_id,
        f"🎉 Payment verified!\nHere is your access:\n\n{product['access']}"
    )

    await query.edit_message_caption(
        caption=f"✅ Approved Txn {txn_id} and access sent to @{data['username']}"
    )

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
    await query.message.reply_text(
        f"✏️ Please type the reason for rejecting transaction `{txn_id}`:",
        parse_mode="Markdown"
    )

async def rejection_reason_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if ADMIN_ID not in awaiting_reasons:
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
        f"🚫 *Payment Rejected*\n\n❌ Your payment for *{product['name']}* has been rejected.\n\n"
        f"🆔 Screenshot ID: `{txn_id}`\n💬 Reason: {reason}\n\n"
        "👉 Please re-check your transaction and upload a valid screenshot.",
        parse_mode="Markdown"
    )

    await update.message.reply_text(f"✅ Sent rejection reason to buyer of Txn {txn_id}.")

# ------------------- PRODUCT MANAGEMENT (NEW step-by-step flows) -------------------
# Conversation states
ADD_CODE, ADD_NAME, ADD_PRICE, ADD_ACCESS, ADD_IMAGE = range(5)
REMOVE_SELECT = 0

# -- Add product conversation
async def addproduct_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin only
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to add products.")
        return ConversationHandler.END

    await update.message.reply_text(
        "🆕 *Add Product* — Step 1/5\n\nSend a unique product *code* (e.g. p4). "
        "Type `auto` to auto-generate a code.",
        parse_mode="Markdown"
    )
    return ADD_CODE

async def addproduct_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    if code.lower() == "auto":
        # auto-generate next code
        idx = 1
        while f"p{idx}" in PRODUCTS:
            idx += 1
        code = f"p{idx}"
    if code in PRODUCTS:
        await update.message.reply_text("⚠️ That code already exists. Send a different code or type `auto`.", parse_mode="Markdown")
        return ADD_CODE

    context.user_data["new_product"] = {"code": code}
    await update.message.reply_text("Step 2/5 — Send the *product name*:", parse_mode="Markdown")
    return ADD_NAME

async def addproduct_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data["new_product"]["name"] = name
    await update.message.reply_text("Step 3/5 — Send the *product price* (number only):")
    return ADD_PRICE

async def addproduct_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        price = int(text)
    except ValueError:
        await update.message.reply_text("⚠️ Price must be a number. Please send the price again:")
        return ADD_PRICE
    context.user_data["new_product"]["price"] = price
    await update.message.reply_text("Step 4/5 — Send the *access link* (URL or text):")
    return ADD_ACCESS

async def addproduct_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    context.user_data["new_product"]["access"] = link
    await update.message.reply_text("Step 5/5 — Send a *product image* (photo) or type /skip to continue without an image.")
    return ADD_IMAGE

async def addproduct_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # store Telegram file_id (persistent) rather than downloading locally
    photo = update.message.photo[-1]
    file_id = photo.file_id
    p = context.user_data["new_product"]
    p["image"] = file_id

    code = p["code"]
    # save product
    PRODUCTS[code] = {"name": p["name"], "price": p["price"], "access": p["access"], "image": p["image"]}
    save_products(PRODUCTS)

    await update.message.reply_text(f"✅ Product *{p['name']}* added with code `{code}`.", parse_mode="Markdown")
    context.user_data.pop("new_product", None)
    return ConversationHandler.END

async def addproduct_skip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    p = context.user_data["new_product"]
    p["image"] = None
    code = p["code"]
    PRODUCTS[code] = {"name": p["name"], "price": p["price"], "access": p["access"], "image": p["image"]}
    save_products(PRODUCTS)

    await update.message.reply_text(f"✅ Product *{p['name']}* added with code `{code}` (no image).", parse_mode="Markdown")
    context.user_data.pop("new_product", None)
    return ConversationHandler.END

async def addproduct_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("new_product", None)
    await update.message.reply_text("❌ Product creation cancelled.")
    return ConversationHandler.END

# -- Remove product conversation (admin only)
async def removeproduct_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not authorized to remove products.")
        return ConversationHandler.END

    if not PRODUCTS:
        await update.message.reply_text("⚠️ No products available to remove.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(f"{p['name']} ({code})", callback_data=f"remove_{code}")]
        for code, p in PRODUCTS.items()
    ]
    await update.message.reply_text("Select a product to remove:", reply_markup=InlineKeyboardMarkup(keyboard))
    return REMOVE_SELECT

async def removeproduct_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # remove_p1 etc
    try:
        _, code = data.split("_", 1)
    except Exception:
        await query.edit_message_text("Invalid selection.")
        return ConversationHandler.END

    if code not in PRODUCTS:
        await query.edit_message_text("❌ Product not found (already removed?).")
        return ConversationHandler.END

    removed = PRODUCTS.pop(code)
    save_products(PRODUCTS)
    await query.edit_message_text(f"🗑️ Removed product: {removed['name']} (code: {code})")
    return ConversationHandler.END

# ------------------- INFO COMMANDS (unchanged) -------------------
async def buyers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not os.path.exists("transactions.txt"):
        await update.message.reply_text("📂 No transactions found.")
        return

    with open("transactions.txt", "r") as f:
        lines = f.readlines()[1:]

    if not lines:
        await update.message.reply_text("📂 No buyers yet.")
        return

    text = "🧾 Buyers List:\n\n" + "".join(lines[-10:])
    await update.message.reply_text(text)

async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_product:
        await update.message.reply_text("🛒 You haven't bought anything yet.")
        return
    product_code = user_product[user_id]
    product = PRODUCTS[product_code]
    await update.message.reply_text(f"🛍️ You purchased: {product['name']} (₹{product['price']})")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠 Commands:\n"
        "/start - Browse products\n"
        "/myorders - View your orders\n"
        "/buyers - (Admin) View transactions\n"
        "/addproduct - (Admin) Guided add product\n"
        "/removeproduct - (Admin) Remove product\n\n"
        "💡 After payment, upload your payment screenshot here."
    )

# ------------------- ERROR HANDLER (unchanged) -------------------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.error(msg="Exception while handling update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("⚠️ An error occurred. Please try again later.")

# ------------------- BOT RUN -------------------
def main():
    app = Application.builder().token(TOKEN).build()

    # Register original handlers (product selection, payments, admin approve/reject, etc.)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(product_callback, pattern="^p"))
    app.add_handler(CallbackQueryHandler(approve_callback, pattern="^approve_"))
    app.add_handler(CallbackQueryHandler(reject_callback, pattern="^reject_"))
    app.add_handler(CommandHandler("buyers", buyers))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("help", help_cmd))

    # Conversation handler for adding product
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("addproduct", addproduct_start)],
        states={
            ADD_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_code)],
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_name)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_price)],
            ADD_ACCESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, addproduct_access)],
            ADD_IMAGE: [
                MessageHandler(filters.PHOTO, addproduct_image),
                CommandHandler("skip", addproduct_skip)
            ],
        },
        fallbacks=[CommandHandler("cancel", addproduct_cancel)],
        per_message=False,
    )
    app.add_handler(add_conv)

    # Conversation handler for removing product
    remove_conv = ConversationHandler(
        entry_points=[CommandHandler("removeproduct", removeproduct_start)],
        states={
            REMOVE_SELECT: [CallbackQueryHandler(removeproduct_callback, pattern="^remove_")]
        },
        fallbacks=[CommandHandler("cancel", lambda u, c: ConversationHandler.END)],
        per_message=False,
    )
    app.add_handler(remove_conv)

    # Register the screenshot handler and rejection reason handler AFTER conversation handlers
    app.add_handler(MessageHandler(filters.PHOTO, payment_screenshot))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, rejection_reason_handler))

    # Error handler
    app.add_error_handler(error_handler)

    logging.info("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
