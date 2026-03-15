export const TOKEN_STORAGE_KEY = "ppn_token";
export const CASE_STORAGE_KEY = "ppn_case_id";
export const JURISDICTION_CASE_STORAGE_KEY = "ppn_jurisdiction_case_id";
export const INCLUDED_SOURCE_IDS_STORAGE_KEY = "ppn_included_source_ids";
export const ARTIFACT_TASKS_STORAGE_KEY = "ppn_artifact_tasks";
export const CHAT_MESSAGES_STORAGE_KEY = "ppn_chat_messages";
export const CHAT_QUESTION_STORAGE_KEY = "ppn_chat_question";
export const SOURCES_FORM_STORAGE_KEY = "ppn_sources_form";
export const STUDIO_FORM_STORAGE_KEY = "ppn_studio_form";

export const RESETTABLE_WORKSPACE_KEYS = [
  CASE_STORAGE_KEY,
  JURISDICTION_CASE_STORAGE_KEY,
  INCLUDED_SOURCE_IDS_STORAGE_KEY,
  ARTIFACT_TASKS_STORAGE_KEY,
  CHAT_MESSAGES_STORAGE_KEY,
  CHAT_QUESTION_STORAGE_KEY,
  SOURCES_FORM_STORAGE_KEY,
  STUDIO_FORM_STORAGE_KEY,
] as const;
