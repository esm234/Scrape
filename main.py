import os
import json
import random
import logging
from typing import List, Dict

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("Environment variable TELEGRAM_TOKEN is not set.")
    exit(1)


async def extract_exam_data(page) -> List[Dict]:
    """
    Extract exam data from the viewscore page.
    Returns list of dicts with the required schema.
    """
    logger.info("Extracting exam data from viewscore page...")

    # Extract exam title and category
    exam_title = ""
    category = ""
    try:
        exam_title_el = await page.query_selector("div.freebirdFormviewerViewHeaderTitle, div.freebirdFormviewerViewHeaderTitleRow")
        if exam_title_el:
            exam_title = await exam_title_el.inner_text()
            exam_title = exam_title.strip()
        else:
            h1 = await page.query_selector("h1")
            if h1:
                exam_title = await h1.inner_text()
                exam_title = exam_title.strip()
    except Exception:
        pass

    if "(" in exam_title and ")" in exam_title:
        start = exam_title.find("(") + 1
        end = exam_title.find(")")
        category = exam_title[start:end].strip()

    questions = await page.query_selector_all("div.freebirdFormviewerViewItemsItemItem")
    if not questions:
        questions = await page.query_selector_all("div[role=listitem]")

    exam_data = []
    for i, q in enumerate(questions, start=1):
        try:
            q_text_el = await q.query_selector("div.freebirdFormviewerViewItemsItemItemTitle, div[role=heading]")
            q_text = (await q_text_el.inner_text()).strip() if q_text_el else ""

            choice_labels = await q.query_selector_all("div.freebirdFormviewerViewItemsItemItemChoice, div[role=radio] label, div[role=radio]")
            choices = []
            for c in choice_labels:
                text = (await c.inner_text()).strip()
                if text:
                    choices.append(text)
            if not choices:
                labels = await q.query_selector_all("label")
                for l in labels:
                    t = (await l.inner_text()).strip()
                    if t:
                        choices.append(t)

            answer = ""
            correct_el = await q.query_selector("[aria-label*='correct'], [aria-label*='صحيح']")
            if correct_el:
                answer = (await correct_el.inner_text()).strip()
            else:
                svgs = await q.query_selector_all("svg")
                for svg in svgs:
                    try:
                        path = await svg.query_selector("path")
                        if path:
                            fill = await path.get_attribute("fill")
                            if fill and ("#34A853" in fill or "green" in fill.lower()):
                                parent = await svg.evaluate_handle("e => e.closest('label') || e.parentElement")
                                if parent:
                                    answer = (await parent.inner_text()).strip()
                                    break
                    except Exception:
                        continue

            if not answer:
                correct_class_el = await q.query_selector(".freebirdFormviewerViewItemsItemCorrectAnswer")
                if correct_class_el:
                    answer = (await correct_class_el.inner_text()).strip()

            if not answer and choices:
                answer = ""

            exam_data.append(
                {
                    "question_number": i,
                    "question": q_text,
                    "type": "اختيار",
                    "choices": choices,
                    "answer": answer,
                    "exam": exam_title,
                    "category": category,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to extract question {i}: {e}")

    return exam_data


async def fill_first_page(page):
    logger.info("Filling first page...")
    try:
        inputs = await page.query_selector_all("input[type=text], input:not([type])")
        input_el = None
        for inp in inputs:
            aria = await inp.get_attribute("aria-label") or ""
            placeholder = await inp.get_attribute("placeholder") or ""
            name = await inp.get_attribute("name") or ""
            if "اسم الطالب" in aria or "اسم الطالب" in placeholder or "اسم الطالب" in name:
                input_el = inp
                break
        if not input_el:
            input_el = inputs[0] if inputs else None
        if input_el:
            await input_el.fill("Bot Test")
            logger.info("Filled 'اسم الطالب' with 'Bot Test'.")
        else:
            logger.warning("Could not find 'اسم الطالب' input field.")
    except Exception as e:
        logger.warning(f"Error filling 'اسم الطالب': {e}")

    try:
        labels = await page.query_selector_all("label")
        checkbox_input = None
        for label in labels:
            text = await label.inner_text()
            if "أقسم" in text:
                for_attr = await label.get_attribute("for")
                if for_attr:
                    checkbox_input = await page.query_selector(f"#{for_attr}")
                else:
                    checkbox_input = await label.query_selector("input[type=checkbox]")
                if checkbox_input:
                    break
        if checkbox_input:
            await checkbox_input.check()
            logger.info("Checked the 'أقسم أنني...' checkbox.")
        else:
            logger.warning("Could not find the checkbox 'أقسم أنني...'.")
    except Exception as e:
        logger.warning(f"Error checking checkbox: {e}")

    try:
        next_btn = await page.query_selector("div[role=button][jsname=V67aGc], div[role=button]:has-text('التالي')")
        if not next_btn:
            buttons = await page.query_selector_all("div[role=button]")
            for b in buttons:
                if "التالي" in await b.inner_text():
                    next_btn = b
                    break
        if next_btn:
            await next_btn.click()
            logger.info("Clicked 'التالي' button.")
        else:
            logger.warning("Could not find 'التالي' button.")
    except Exception as e:
        logger.warning(f"Error clicking 'التالي' button: {e}")


async def fill_second_page(page):
    logger.info("Filling second page with random choices...")
    try:
        questions = await page.query_selector_all("div.freebirdFormviewerViewItemsItemItem")
        if not questions:
            questions = await page.query_selector_all("div[role=listitem]")
        if not questions:
            logger.warning("No questions found on second page.")
            return

        for q in questions:
            radios = await q.query_selector_all("div[role=radio]")
            if not radios:
                radios = await q.query_selector_all("input[type=radio]")
            if radios:
                choice = random.choice(radios)
                try:
                    await choice.click()
                except Exception:
                    try:
                        label = await choice.query_selector("label")
                        if label:
                            await label.click()
                        else:
                            await choice.evaluate("el => el.click()")
                    except Exception:
                        pass
            else:
                logger.warning("No radio buttons found for a question.")

        submit_btn = await page.query_selector("div[role=button][jsname=V67aGc], div[role=button]:has-text('إرسال')")
        if not submit_btn:
            buttons = await page.query_selector_all("div[role=button]")
            for b in buttons:
                if "إرسال" in await b.inner_text():
                    submit_btn = b
                    break
        if submit_btn:
            await submit_btn.click()
            logger.info("Clicked 'إرسال' button.")
        else:
            logger.warning("Could not find 'إرسال' button.")
    except Exception as e:
        logger.warning(f"Error filling second page: {e}")


async def click_view_score(page) -> bool:
    logger.info("Trying to click 'عرض النتيجة' button...")
    try:
        btn = await page.query_selector("div[role=button]:has-text('عرض النتيجة')")
        if not btn:
            btn = await page.query_selector("button:has-text('عرض النتيجة')")
        if not btn:
            all_btns = await page.query_selector_all("div[role=button], button, input[type=button]")
            for b in all_btns:
                if (await b.inner_text()).strip() == "عرض النتيجة":
                    btn = b
                    break
        if btn:
            await btn.click()
            logger.info("Clicked 'عرض النتيجة' button.")
            return True
        else:
            logger.warning("Could not find 'عرض النتيجة' button.")
            return False
    except Exception as e:
        logger.warning(f"Error clicking 'عرض النتيجة' button: {e}")
        return False


async def scrape_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or len(context.args) != 1:
        await update.message.reply_text("❗️ الرجاء إرسال رابط الفورم مع الأمر: /scrape <form_url>")
        return

    form_url = context.args[0]
    chat_id = update.effective_chat.id

    logger.info(f"Received /scrape command from chat_id={chat_id} with URL: {form_url}")

    await update.message.reply_text("⏳ جاري معالجة الفورم...")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context_browser = await browser.new_context()
            page = await context_browser.new_page()

            logger.info("Navigating to form URL...")
            await page.goto(form_url, timeout=30000)

            await page.wait_for_selector("form", timeout=15000)

            await fill_first_page(page)

            try:
                await page.wait_for_selector("div[role=radio], input[type=radio]", timeout=15000)
            except PlaywrightTimeoutError:
                logger.warning("Timeout waiting for second page radio buttons.")

            await fill_second_page(page)

            try:
                await page.wait_for_selector("div[role=button]:has-text('عرض النتيجة')", timeout=15000)
            except PlaywrightTimeoutError:
                logger.warning("Timeout waiting for confirmation page with 'عرض النتيجة' button.")

            if not await click_view_score(page):
                await update.message.reply_text("⚠️ تعذر استخراج النتائج.")
                logger.error("Failed to find or click 'عرض النتيجة' button.")
                await browser.close()
                return

            await page.wait_for_load_state("networkidle", timeout=15000)

            exam_data = await extract_exam_data(page)
            if not exam_data:
                await update.message.reply_text("⚠️ تعذر استخراج النتائج.")
                logger.error("No exam data extracted.")
                await browser.close()
                return

            with open("exam.json", "w", encoding="utf-8") as f:
                json.dump(exam_data, f, ensure_ascii=False, indent=2)

            logger.info("Exam data saved to exam.json")

            with open("exam.json", "rb") as f:
                await context.bot.send_document(chat_id=chat_id, document=f, filename="exam.json")

            await browser.close()
            logger.info("Scraping completed successfully.")

    except Exception as e:
        logger.error(f"Exception during scraping: {e}")
        await update.message.reply_text("⚠️ تعذر استخراج النتائج.")


def main():
    logger.info("Starting Telegram bot...")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("scrape", scrape_command))

    app.run_polling()


if __name__ == "__main__":
    main()
