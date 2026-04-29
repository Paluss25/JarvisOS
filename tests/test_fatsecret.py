from src.agents.don.clients.fatsecret import FatSecretClient

def test_parse_description_standard():
    desc = "Per 100g - Calories: 165kcal | Fat: 3.60g | Carbs: 0.00g | Protein: 31.02g"
    result = FatSecretClient._parse_description(desc)
    assert result["calories"] == 165
    assert result["protein"] == 31.02
    assert result["carbs"] == 0
    assert result["fat"] == 3.60
    assert result["serving_g"] == 100

def test_parse_description_different_serving():
    desc = "Per 200g - Calories: 330kcal | Fat: 7.20g | Carbs: 0.00g | Protein: 62.04g"
    result = FatSecretClient._parse_description(desc)
    assert result["serving_g"] == 200
    assert result["calories"] == 330

def test_parse_description_empty():
    result = FatSecretClient._parse_description("")
    assert result["calories"] == 0
    assert result["serving_g"] == 100
