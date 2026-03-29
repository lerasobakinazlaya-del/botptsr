def build_mode_instruction(mode_config: dict) -> str:
    def describe(value: int) -> str:
        if value <= 1:
            return "почти отсутствует"
        if value <= 3:
            return "низко"
        if value <= 5:
            return "умеренно"
        if value <= 7:
            return "заметно"
        if value <= 9:
            return "сильно"
        return "очень сильно"

    return (
        "Калибровка режима:\n"
        f"- Тепло и эмпатия ощущаются {describe(mode_config['warmth'])}.\n"
        f"- Игривость или флирт ощущаются {describe(mode_config['flirt'])}.\n"
        f"- Глубина и рефлексия ощущаются {describe(mode_config['depth'])}.\n"
        f"- Структура и логика ощущаются {describe(mode_config['structure'])}.\n"
        f"- Ведущая или доминирующая энергия ощущается {describe(mode_config['dominance'])}.\n"
        f"- Инициативность ощущается {describe(mode_config['initiative'])}.\n"
        f"- Внешняя эмоциональная выразительность ощущается {describe(mode_config['emoji_level'])}.\n"
        "Режим должен окрашивать ответ изнутри и тихо менять его фактуру, а не звучать как включенный пресет."
    )
