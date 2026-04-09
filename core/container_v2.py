# Updated container using AIServiceV2 and PromptBuilderV2

from services.ai_service_v2 import AIServiceV2 as AIService
from services.prompt_builder_v2 import PromptBuilderV2 as PromptBuilder

# import rest from original container
from core.container import *

# NOTE:
# This file overrides AIService and PromptBuilder with v2 versions.
# To activate, change import in main.py:
# from core.container import Container
# -> from core.container_v2 import Container
