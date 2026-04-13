import STATIC_SCALE_QUESTIONS from '../data/scale_questions.json';

const CURRENT_STACK_ID = 'current_stack';

export function buildScaleQuestions(earlyTools = []) {
  const toolNames = (Array.isArray(earlyTools) ? earlyTools : [])
    .map((t) => (t?.name || '').trim())
    .filter(Boolean);
  const uniqueToolNames = [...new Set(toolNames)];

  if (!uniqueToolNames.length) return STATIC_SCALE_QUESTIONS;

  return STATIC_SCALE_QUESTIONS.map((q) => {
    if (q.id !== CURRENT_STACK_ID) return q;
    return {
      ...q,
      options: [...uniqueToolNames, 'None of these yet'],
    };
  });
}
