from app.db import SessionLocal
from app.models import Decision, Project

with SessionLocal() as db:
    project = db.query(Project).filter_by(name="atlas-demo").one_or_none()
    if project is None:
        project = Project(name="atlas-demo", summary="Demo project for Atlas.")
        db.add(project)
        db.flush()
    decision = Decision(project_id=project.id, decision="Use FastAPI for the Atlas backend.", reason="Small typed API surface for MCP and dashboard.", affected_files=["backend/app/main.py"])
    db.add(decision)
    db.commit()
    print(f"Seeded and read: {db.get(Decision, decision.id).decision}")
