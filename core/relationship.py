# relationship.py

class RelationshipState:
    def __init__(self):
        self.trust_level = 1  # 1-10
        self.intimacy_level = 1  # 1-10
        self.days_active = 0

    def increase_trust(self, amount=1):
        self.trust_level = min(10, self.trust_level + amount)

    def increase_intimacy(self, amount=1):
        self.intimacy_level = min(10, self.intimacy_level + amount)

    def build_context(self):
        return f"""
        Уровень доверия: {self.trust_level}/10.
        Уровень близости: {self.intimacy_level}/10.
        """