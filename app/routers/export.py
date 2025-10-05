from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from ..services.cache import get_payload
from pathlib import Path
import io, csv, re, tempfile, os, json
import genanki

router = APIRouter()

def int_id_from_hash(h: str, salt: int = 0) -> int:
    return int(h[:10], 16) + salt

@router.get("/export/csv")
def export_csv(id: str = Query(...), title: str = Query("StudyBuddy")):
    payload = get_payload(id)
    cards_json = payload.get("cards_json")
    if not cards_json: raise HTTPException(404, "No cards cached for this document.")
    try:
        cards = json.loads(cards_json)["cards"]
    except Exception:
        raise HTTPException(500, "Cached cards JSON is invalid.")
    if not cards: raise HTTPException(404, "No cards to export.")

    sio = io.StringIO(newline="")
    writer = csv.writer(sio)
    writer.writerow(["type", "front", "back", "source"])
    for c in cards:
        writer.writerow([c.get("type",""), c.get("front",""), c.get("back",""), c.get("source","") or ""])
    data = sio.getvalue().encode("utf-8-sig")
    filename = f"{re.sub(r'[^A-Za-z0-9._-]+','_', title)}-cards.csv"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(io.BytesIO(data), media_type="text/csv", headers=headers)

@router.get("/export/apkg")
def export_apkg(id: str = Query(...), title: str = Query("StudyBuddy")):
    payload = get_payload(id)
    cards_json = payload.get("cards_json")
    if not cards_json: raise HTTPException(404, "No cards cached for this document.")
    try:
        cards = json.loads(cards_json)["cards"]
    except Exception:
        raise HTTPException(500, "Cached cards JSON is invalid.")
    if not cards: raise HTTPException(404, "No cards to export.")

    deck_id = int_id_from_hash(id, 1000)
    model_basic_id = int_id_from_hash(id, 2000)
    model_cloze_id = int_id_from_hash(id, 3000)

    deck_title = f"{title} – StudyBuddy"
    deck = genanki.Deck(deck_id, deck_title)

    basic_model = genanki.Model(
        model_basic_id,
        "StudyBuddy Basic",
        fields=[{"name":"Front"},{"name":"Back"},{"name":"Source"}],
        templates=[{
            "name":"Card 1",
            "qfmt":"{{Front}}",
            "afmt":"{{Front}}<hr id=answer>{{Back}}<div style='color:#6b7280;margin-top:6px'>{{Source}}</div>",
        }],
        css=".card { font-family: Inter, Arial; font-size: 18px; }",
    )

    cloze_model = genanki.Model(
        model_cloze_id,
        "StudyBuddy Cloze",
        fields=[{"name":"Text"},{"name":"Extra"},{"name":"Source"}],
        templates=[{
            "name":"Cloze",
            "qfmt":"{{cloze:Text}}",
            "afmt":"{{cloze:Text}}<hr id=answer>{{Extra}}<div style='color:#6b7280;margin-top:6px'>{{Source}}</div>",
        }],
        css=".card { font-family: Inter, Arial; font-size: 18px; }",
        model_type=genanki.Model.CLOZE,
    )

    for c in cards:
        ctype = (c.get("type") or "").lower()
        front = c.get("front",""); back = c.get("back",""); src = c.get("source","") or ""
        if ctype == "cloze" and "{{c" in front:
            note = genanki.Note(model=cloze_model, fields=[front, back, src])
        else:
            note = genanki.Note(model=basic_model, fields=[front, back, src])
        deck.add_note(note)

    pkg = genanki.Package(deck)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".apkg") as tmp:
        pkg.write_to_file(tmp.name); tmp_path = tmp.name

    filename = f"{re.sub(r'[^A-Za-z0-9._-]+','_', title)}-studybuddy.apkg"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    data = Path(tmp_path).read_bytes()
    try:
        return StreamingResponse(io.BytesIO(data), media_type="application/octet-stream", headers=headers)
    finally:
        try: os.remove(tmp_path)
        except: pass
