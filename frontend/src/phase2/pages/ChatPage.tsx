import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import ChatUI from '../components/chat/ChatUI';
import type { RichMessage } from '../components/chat/ChatUI';
import { getMessages, createPlanStream, approvePlanStream } from '../api/client';
import type { AgentId, PipelineStage, ProgressEvent as ApiProgressEvent } from '../api/client';
import { useUiAgents } from '../context/UiAgentsContext';

// Stream-mode debug logs are kept in legacy flow; plan-only mode does not use them.

interface ChatPageProps {
  conversationId?: string;
}

export default function ChatPage({ conversationId: propConvId }: ChatPageProps) {
  const [messages, setMessages] = useState<RichMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>(propConvId);
  const [loading, setLoading] = useState(false);
  const [initLoading, setInitLoading] = useState(true);
  const [model, setModel] = useState<string | undefined>();
  const navigate = useNavigate();

  const { activeAgentId } = useUiAgents();

  const [conversationStageOutputs, setConversationStageOutputs] = useState<Record<string, string>>({});

  const loadedForRef = useRef<string | undefined>('__uninitialized__');
  useEffect(() => {
    if (loadedForRef.current === propConvId) return;
    loadedForRef.current = propConvId;

    setInitLoading(true);
    setMessages([]);
    setConversationStageOutputs({});
    setConversationId(propConvId);

    getMessages(propConvId)
      .then((data) => {
        const loadedAgentId = (data.agentId ?? activeAgentId) as AgentId;
        setMessages(
          (data.messages ?? []).map((m) => {
            const base = { ...m, outputFile: m.outputFile, agentId: loadedAgentId };
            // For business-research assistant messages that have content but no
            // pipeline state (pipeline state is in-memory only, never persisted),
            // synthesise a done pipeline so the Download PDF button shows on reload.
            // Use a 500-char threshold to skip short chat replies (not reports).
            if (
              (loadedAgentId === 'business-research' || loadedAgentId === 'business-strategy') &&
              m.role === 'assistant' &&
              m.content.length > 500 &&
              !m.outputFile
            ) {
              return {
                ...base,
                pipeline: {
                  currentStage: 'done' as PipelineStage,
                  agentId: loadedAgentId,
                  stageOutputs: data.lastStageOutputs ?? {},
                  progressEvents: [],
                  outputFile: undefined,
                  error: undefined,
                },
              };
            }
            return base;
          })
        );
        if (data.conversationId) setConversationId(data.conversationId);
        if (data.lastStageOutputs) setConversationStageOutputs(data.lastStageOutputs);
      })
      .catch(() => setMessages([]))
      .finally(() => setInitLoading(false));
  }, [propConvId, activeAgentId]);

  const runStream = async (
    userMessage: string,
    _retryFromStage?: PipelineStage,
    _retryStageOutputs?: Record<string, string>
  ) => {
    setLoading(true);

    // New run: clear any stored pipeline snapshot for the last message so we only
    // keep skills/pages for the most recent reply.
    try {
      const key = `lastPipeline:${conversationId ?? ''}`;
      window.localStorage.removeItem(key);
    } catch {
      // ignore
    }

    setMessages((prev) => [...prev, { role: 'user', content: userMessage }]);
    setMessages((prev) => [...prev, { role: 'assistant', content: '', agentId: activeAgentId }]);

    try {
      // Plan-only: every user message generates a plan. Execution happens ONLY via approve API.
      const lastDraftPlanId = (() => {
        for (let i = messages.length - 1; i >= 0; i--) {
          const m = messages[i] as any;
          if (m?.role === 'assistant' && m?.kind === 'plan' && typeof m?.planId === 'string') return m.planId as string;
        }
        return undefined;
      })();
      const plan = await createPlanStream({
        message: userMessage,
        conversationId,
        agentId: activeAgentId,
        cancelPlanId: lastDraftPlanId,
        callbacks: {
          onStage: (stage, _label, _idx) => {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  pipeline: {
                    currentStage: stage as any,
                    agentId: activeAgentId,
                    stageOutputs: conversationStageOutputs,
                    progressEvents: last.pipeline?.progressEvents ?? [],
                    outputFile: undefined,
                    error: undefined,
                  },
                };
              }
              return updated;
            });
          },
          onProgress: (event: ApiProgressEvent) => {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  pipeline: {
                    currentStage: last.pipeline?.currentStage ?? ('thinking' as PipelineStage),
                    agentId: activeAgentId,
                    stageOutputs: last.pipeline?.stageOutputs ?? conversationStageOutputs,
                    progressEvents: [...(last.pipeline?.progressEvents ?? []), event],
                    outputFile: undefined,
                    error: undefined,
                  },
                };
              }
              return updated;
            });
          },
        },
      });

      if (plan.conversationId) {
        setConversationId(plan.conversationId);
        if (plan.conversationId !== propConvId) {
          loadedForRef.current = plan.conversationId;
          navigate(`/chat/${plan.conversationId}`, { replace: true });
        }
      }

      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === 'assistant') {
          updated[updated.length - 1] = {
            ...last,
            content: plan.planMarkdown ?? '',
            kind: 'plan',
            planId: plan.planId,
            messageId: plan.planMessageId,
            pipeline: {
              currentStage: 'done',
              agentId: activeAgentId,
              stageOutputs: conversationStageOutputs,
              progressEvents: last.pipeline?.progressEvents ?? [],
              outputFile: undefined,
              error: undefined,
            },
          } as any;
        }
        return updated;
      });
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Something went wrong';
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === 'assistant') {
          updated[updated.length - 1] = { ...last, content: `⚠️ ${errorMsg}` };
        }
        return updated;
      });
    } finally {
      setLoading(false);
    }
  };

  const handleApprovePlan = async (planId: string, planMarkdown: string) => {
    setLoading(true);
    setMessages((prev) => [...prev, { role: 'assistant', content: '', agentId: activeAgentId } as any]);
    try {
      const result = await approvePlanStream({
        planId,
        conversationId,
        planMarkdown,
        agentId: activeAgentId,
        callbacks: {
          onStage: (stage, _label, _idx) => {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  pipeline: {
                    currentStage: stage as any,
                    agentId: activeAgentId,
                    stageOutputs: conversationStageOutputs,
                    progressEvents: last.pipeline?.progressEvents ?? [],
                    outputFile: undefined,
                    error: undefined,
                  },
                };
              }
              return updated;
            });
          },
          onProgress: (event: ApiProgressEvent) => {
            const meta = (event as any)?.meta;
            if (
              meta?.kind === 'checklist-update' &&
              typeof meta?.planId === 'string' &&
              meta.planId === planId &&
              typeof meta?.planMarkdown === 'string'
            ) {
              setMessages((prev) =>
                prev.map((m: any) =>
                  m?.role === 'assistant' && m?.kind === 'plan' && m?.planId === planId
                    ? { ...m, content: meta.planMarkdown }
                    : m
                )
              );
            }
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === 'assistant' && last.pipeline) {
                updated[updated.length - 1] = {
                  ...last,
                  pipeline: {
                    ...last.pipeline,
                    progressEvents: [...(last.pipeline.progressEvents ?? []), event],
                  },
                };
              }
              return updated;
            });
          },
          onToken: (token) => {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = { ...last, content: (last.content ?? '') + token };
              }
              return updated;
            });
          },
        },
      });

      if (result.conversationId) setConversationId(result.conversationId);
      if (result.model) setModel(result.model);
      if (result.stageOutputs) setConversationStageOutputs((prev) => ({ ...prev, ...result.stageOutputs }));

      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === 'assistant' && result.messageId) {
          updated[updated.length - 1] = { ...last, messageId: result.messageId } as any;
        }
        return updated;
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async (content: string) => {
    await runStream(content);
  };

  const handleRetry = async (
    fromStage: PipelineStage,
    stageOutputs: Record<string, string>,
    originalMessage: string
  ) => {
    setMessages((prev) => prev.slice(0, -1));
    await runStream(originalMessage, fromStage, stageOutputs);
  };

  const retryHandlers = messages.map((msg, idx) => {
    if (msg.role !== 'assistant' || !msg.pipeline) return undefined;
    const userMsg = messages[idx - 1];
    const originalMessage = userMsg?.role === 'user' ? userMsg.content : '';
    return (fromStage: PipelineStage, stageOutputs: Record<string, string>) => {
      void handleRetry(fromStage, stageOutputs, originalMessage);
    };
  });

  if (initLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-3 text-slate-400">
          <div className="w-5 h-5 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm">Loading conversation…</span>
        </div>
      </div>
    );
  }

  return (
    <ChatUI
      messages={messages}
      onSend={handleSend}
      onApprovePlan={handleApprovePlan}
      loading={loading}
      agentId={activeAgentId}
      subtitle={model ? `${activeAgentId} · ${model}` : undefined}
      retryHandlers={retryHandlers}
    />
  );
}
