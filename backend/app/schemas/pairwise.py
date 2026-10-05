from pydantic import BaseModel, ConfigDict, model_validator


class PairwisePair(BaseModel):
    project_a_id: str
    project_a_title: str
    project_b_id: str
    project_b_title: str


class PairwiseSubmit(BaseModel):
    project_a_id: str
    project_b_id: str
    winner_id: str

    @model_validator(mode="after")
    def validate_winner(self):
        if self.project_a_id == self.project_b_id:
            raise ValueError("Can't compare a project against itself.")
        if self.winner_id not in (self.project_a_id, self.project_b_id):
            raise ValueError("winner_id must be either project_a_id or project_b_id.")
        return self


class PairwiseRankRow(BaseModel):
    project_id: str
    project_title: str
    team_name: str = ""
    strength: float
    comparisons: int
