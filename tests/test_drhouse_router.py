from src.agents.coh.router import classify

def test_food_routes_to_nutrition():
    plan = classify("Ho mangiato una pizza margherita")
    assert "don" in plan.consult

def test_training_routes_to_dos():
    plan = classify("How was my run today?")
    assert "dos" in plan.consult

def test_cross_domain():
    plan = classify("Had pizza, running tomorrow morning")
    assert "don" in plan.consult
    assert "dos" in plan.consult

def test_medical_gate():
    plan = classify("I have chest pain after running")
    assert plan.medical_gate_first is True

def test_image_routes_to_nutrition():
    plan = classify("What's this?", has_image=True)
    assert "don" in plan.consult

def test_strategic_is_direct():
    plan = classify("What's my progress this week?")
    assert plan.is_strategic is True

def test_barcode_routes_to_nutrition():
    plan = classify("8001234567890", has_barcode=True)
    assert "don" in plan.consult

def test_italian_sport():
    plan = classify("Come è andato l'allenamento di oggi?")
    assert "dos" in plan.consult

def test_generic_question_is_strategic():
    plan = classify("How are you?")
    assert plan.is_strategic is True
