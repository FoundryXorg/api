name: PDF robot (v1.0.0 - big Telegram files, PDF covers)
# Runs when the Apps Script wakes it up (a big file was sent to the bot / a PDF needs a cover) and every 15 minutes as a safety net.
on:
  repository_dispatch:
    types: [tg-big, pdf-covers]
  workflow_dispatch:
  schedule:
    - cron: '*/15 * * * *'
permissions:
  contents: write
concurrency:
  group: pdfrobot
  cancel-in-progress: false
jobs:
  robot:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@v4
        with:
          sparse-checkout: |
            scripts
            pdf
            pdf-previews
          sparse-checkout-cone-mode: true
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install
        run: pip install pymupdf requests pyrogram tgcrypto
      - name: Prepare (import big files, make covers)
        env:
          SCRIPT_URL: ${{ vars.SCRIPT_URL || secrets.SCRIPT_URL }}
          AUTOMATION_KEY: ${{ secrets.AUTOMATION_KEY }}
          TG_BOT_TOKEN: ${{ secrets.TG_BOT_TOKEN }}
          TG_API_ID: ${{ secrets.TG_API_ID }}
          TG_API_HASH: ${{ secrets.TG_API_HASH }}
        run: python scripts/pdf_robot.py prepare
      - name: Commit and push
        run: |
          git config user.name "font-foundry-bot"
          git config user.email "bot@users.noreply.github.com"
          git add --sparse -A pdf pdf-previews
          if git diff --cached --quiet; then echo "no change"; exit 0; fi
          git commit -m "PDF robot: new files / covers"
          for i in 1 2 3 4; do git pull --rebase -X theirs && git push && break || sleep 6; done
      - name: Register in the library and tell Telegram
        env:
          SCRIPT_URL: ${{ vars.SCRIPT_URL || secrets.SCRIPT_URL }}
          AUTOMATION_KEY: ${{ secrets.AUTOMATION_KEY }}
          TG_BOT_TOKEN: ${{ secrets.TG_BOT_TOKEN }}
        run: python scripts/pdf_robot.py register
