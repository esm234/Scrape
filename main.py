import os
import json
import random
import logging
from typing import List, Dict

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("Environment variable TELEGRAM_TOKEN is not set.")
    exit(1)


def extract_exam_data(page) -> List[Dict]:
    """
    Extract exam data from the viewscore page.
    Returns list of dicts with the required schema.
    """
    logger.info("Extracting exam data from viewscore page...")

    # Extract exam title and category
    # Exam title example: "الاختبار الأول (التناظر اللفظي)"
    # We will parse category from parentheses if possible.
    exam_title = ""
    category = ""
    try:
        # The exam title is usually in a header element
        exam_title_el = page.query_selector("div.freebirdFormviewerViewHeaderTitle, div.freebirdFormviewerViewHeaderTitleRow")
        if exam_title_el:
            exam_title = exam_title_el.inner_text().strip()
        else:
            # fallback: try h1 or h2
            h1 = page.query_selector("h1")
            if h1:
                exam_title = h1.inner_text().strip()
    except Exception:
        pass

    if "(" in exam_title and ")" in exam_title:
        start = exam_title.find("(") + 1
        end = exam_title.find(")")
        category = exam_title[start:end].strip()

    # Questions container: each question is usually a div with role="listitem" or class containing "freebirdFormviewerViewItemsItemItem"
    # We will try to find all question blocks
    questions = page.query_selector_all("div.freebirdFormviewerViewItemsItemItem")
    if not questions:
        # fallback: try role=listitem
        questions = page.query_selector_all("div[role=listitem]")

    exam_data = []
    for i, q in enumerate(questions, start=1):
        try:
            # Question text
            q_text_el = q.query_selector("div.freebirdFormviewerViewItemsItemItemTitle, div[role=heading]")
            q_text = q_text_el.inner_text().strip() if q_text_el else ""

            # Choices: usually radio buttons or labels inside the question block
            choice_labels = q.query_selector_all("div.freebirdFormviewerViewItemsItemItemChoice, div[role=radio] label, div[role=radio]")
            choices = []
            for c in choice_labels:
                text = c.inner_text().strip()
                if text:
                    choices.append(text)
            if not choices:
                # fallback: find labels inside question
                labels = q.query_selector_all("label")
                for l in labels:
                    t = l.inner_text().strip()
                    if t:
                        choices.append(t)

            # Correct answer: usually marked with a green check or special class
            # Google Forms quiz mode marks correct answers with aria-label containing "correct" or a green check icon
            answer = ""
            # Try to find element with aria-label containing "correct"
            correct_el = q.query_selector("[aria-label*='correct'], [aria-label*='صحيح']")
            if correct_el:
                answer = correct_el.inner_text().strip()
            else:
                # Try to find element with a green check icon (svg with fill green)
                svgs = q.query_selector_all("svg")
                for svg in svgs:
                    try:
                        path = svg.query_selector("path")
                        if path:
                            fill = path.get_attribute("fill")
                            if fill and ("#34A853" in fill or "green" in fill.lower()):
                                # The parent label or sibling text is the answer
                                parent = svg.evaluate_handle("e => e.closest('label') || e.parentElement")
                                if parent:
                                    answer = parent.inner_text().strip()
                                    break
                    except Exception:
                        continue

            # If still no answer, try to find element with class indicating correct answer
            if not answer:
                correct_class_el = q.query_selector(".freebirdFormviewerViewItemsItemCorrectAnswer")
                if correct_class_el:
                    answer = correct_class_el.inner_text().strip()

            # If still no answer, fallback to empty string
            if not answer and choices:
                # Sometimes the first choice is correct? No, better leave empty
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


def fill_first_page(page):
    logger.info("Filling first page...")
    # Fill "اسم الطالب" text input with "Bot Test"
    try:
        # Find input with label containing "اسم الطالب"
        label_el = page.query_selector("div[role=heading] ~ div label")
        input_el = None
        # Try to find input by placeholder or aria-label or name
        inputs = page.query_selector_all("input[type=text], input:not([type])")
        for inp in inputs:
            # Check aria-label or placeholder or name attribute
            aria = inp.get_attribute("aria-label") or ""
            placeholder = inp.get_attribute("placeholder") or ""
            name = inp.get_attribute("name") or ""
            if "اسم الطالب" in aria or "اسم الطالب" in placeholder or "اسم الطالب" in name:
                input_el = inp
                break
        if not input_el:
            # fallback: first text input
            input_el = inputs[0] if inputs else None
        if input_el:
            input_el.fill("Bot Test")
            logger.info("Filled 'اسم الطالب' with 'Bot Test'.")
        else:
            logger.warning("Could not find 'اسم الطالب' input field.")
    except Exception as e:
        logger.warning(f"Error filling 'اسم الطالب': {e}")

    # Check the checkbox "أقسم أنني..."
    try:
        # Find checkbox input with label containing "أقسم"
        labels = page.query_selector_all("label")
        checkbox_input = None
        for label in labels:
            text = label.inner_text()
            if "أقسم" in text:
                # find associated input checkbox
                for_attr = label.get_attribute("for")
                if for_attr:
                    checkbox_input = page.query_selector(f"#{for_attr}")
                else:
                    # maybe input inside label
                    checkbox_input = label.query_selector("input[type=checkbox]")
                if checkbox_input:
                    break
        if checkbox_input:
            checkbox_input.check()
            logger.info("Checked the 'أقسم أنني...' checkbox.")
        else:
            logger.warning("Could not find the checkbox 'أقسم أنني...'.")
    except Exception as e:
        logger.warning(f"Error checking checkbox: {e}")

    # Click "التالي" button
    try:
        next_btn = page.query_selector("div[role=button][jsname=V67aGc], div[role=button]:has-text('التالي')")
        if not next_btn:
            # fallback: button with text "التالي"
            buttons = page.query_selector_all("div[role=button]")
            for b in buttons:
                if "التالي" in b.inner_text():
                    next_btn = b
                    break
        if next_btn:
            next_btn.click()
            logger.info("Clicked 'التالي' button.")
        else:
            logger.warning("Could not find 'التالي' button.")
    except Exception as e:
        logger.warning(f"Error clicking 'التالي' button: {e}")


def fill_second_page(page):
    logger.info("Filling second page with random choices...")
    # For each question, select a random radio button
    try:
        # Questions container: div with role=listitem or class containing "freebirdFormviewerViewItemsItemItem"
        questions = page.query_selector_all("div.freebirdFormviewerViewItemsItemItem")
        if not questions:
            questions = page.query_selector_all("div[role=listitem]")
        if not questions:
            logger.warning("No questions found on second page.")
            return

        for q in questions:
            radios = q.query_selector_all("div[role=radio]")
            if not radios:
                # fallback: input radio inside question
                radios = q.query_selector_all("input[type=radio]")
            if radios:
                choice = random.choice(radios)
                # click the radio button div or input
                try:
                    choice.click()
                except Exception:
                    # fallback: try to click label or input
                    try:
                        label = choice.query_selector("label")
                        if label:
                            label.click()
                        else:
                            choice.evaluate("el => el.click()")
                    except Exception:
                        pass
            else:
                logger.warning("No radio buttons found for a question.")
        # Click "إرسال" button
        submit_btn = page.query_selector("div[role=button][jsname=V67aGc], div[role=button]:has-text('إرسال')")
        if not submit_btn:
            buttons = page.query_selector_all("div[role=button]")
            for b in buttons:
                if "إرسال" in b.inner_text():
                    submit_btn = b
                    break
        if submit_btn:
            submit_btn.click()
            logger.info("Clicked 'إرسال' button.")
        else:
            logger.warning("Could not find 'إرسال' button.")
    except Exception as e:
        logger.warning(f"Error filling second page: {e}")


def click_view_score(page) -> bool:
    logger.info("Trying to click 'عرض النتيجة' button...")
    try:
        # The button might be a div with role=button and text "عرض النتيجة"
        btn = page.query_selector("div[role=button]:has-text('عرض النتيجة')")
        if not btn:
            # fallback: button element or input[type=button]
            btn = page.query_selector("button:has-text('عرض النتيجة')")
        if not btn:
            # fallback: any element with exact text
            all_btns = page.query_selector_all("div[role=button], button, input[type=button]")
            for b in all_btns:
                if b.inner_text().strip() == "عرض النتيجة":
                    btn = b
                    break
        if btn:
            btn.click()
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
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context_browser = browser.new_context()
            page = context_browser.new_page()

            logger.info("Navigating to form URL...")
            page.goto(form_url, timeout=30000)

            # Wait for form to load
            page.wait_for_selector("form", timeout=15000)

            # Fill first page
            fill_first_page(page)

            # Wait for second page to load (detect by presence of radio buttons)
            try:
                page.wait_for_selector("div[role=radio], input[type=radio]", timeout=15000)
            except PlaywrightTimeoutError:
                logger.warning("Timeout waiting for second page radio buttons.")

            # Fill second page
            fill_second_page(page)

            # Wait for confirmation page (after submit)
            try:
                page.wait_for_selector("div[role=button]:has-text('عرض النتيجة')", timeout=15000)
            except PlaywrightTimeoutError:
                logger.warning("Timeout waiting for confirmation page with 'عرض النتيجة' button.")

            # Click "عرض النتيجة"
            if not click_view_score(page):
                await update.message.reply_text("⚠️ تعذر استخراج النتائج.")
                logger.error("Failed to find or click 'عرض النتيجة' button.")
                browser.close()
                return

            # Wait for viewscore page to load
            page.wait_for_load_state("networkidle", timeout=15000)

            # Extract exam data
            exam_data = extract_exam_data(page)
            if not exam_data:
                await update.message.reply_text("⚠️ تعذر استخراج النتائج.")
                logger.error("No exam data extracted.")
                browser.close()
                return

            # Save to exam.json
            with open("exam.json", "w", encoding="utf-8") as f:
                json.dump(exam_data, f, ensure_ascii=False, indent=2)

            logger.info("Exam data saved to exam.json")

            # Send exam.json file
            with open("exam.json", "rb") as f:
                await context.bot.send_document(chat_id=chat_id, document=f, filename="exam.json")

            browser.close()
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
