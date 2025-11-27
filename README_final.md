# CSSA Shift Swap — Final (Google Sheet only)

Files included:
- app_full_final.py — Streamlit app (entrypoint)
- requirements_final.txt — Python dependencies

How to deploy (Streamlit Cloud):
1. Create a new Streamlit app connected to your GitHub repository.
2. Set the main file to `app_full_final.py`.
3. Ensure `requirements_final.txt` is present in the repo root.
4. Deploy and open the app URL.
5. In the sidebar click **Load roster from Google Sheet** to pull your live roster.
6. Login via the select username. Test swaps. To persist swaps locally, use Admin → Users & Roles → Download updated roster (.xlsx).

Notes:
- This version reads the provided Google Sheet only. No automatic Google writeback is enabled.
- For writeback to Google Sheets, provide a service account JSON in Streamlit secrets as 'gcp_service_account' and I can enable that later.
