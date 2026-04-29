from src.agents.coh.medical import screen_input, ApprovalStatus

def test_red_flag_not_approved():
    result = screen_input("I have chest pain after running")
    assert result.status == ApprovalStatus.NOT_APPROVED
    assert result.escalation_advice

def test_caution_approved_with_constraints():
    result = screen_input("My knee hurts after the workout")
    assert result.status == ApprovalStatus.APPROVED_WITH_CONSTRAINTS
    assert len(result.constraints) > 0

def test_normal_approved():
    result = screen_input("I had chicken and rice for lunch")
    assert result.status == ApprovalStatus.APPROVED

def test_italian_red_flag():
    result = screen_input("Ho dolore al petto")
    assert result.status == ApprovalStatus.NOT_APPROVED

def test_medication_caution():
    result = screen_input("I'm taking medication for blood pressure")
    assert result.status == ApprovalStatus.APPROVED_WITH_CONSTRAINTS
    assert any("medication" in c.lower() for c in result.constraints)

def test_eating_disorder_caution():
    result = screen_input("I think I have an eating disorder")
    assert result.status == ApprovalStatus.APPROVED_WITH_CONSTRAINTS
    assert any("restrictive" in c.lower() for c in result.constraints)
