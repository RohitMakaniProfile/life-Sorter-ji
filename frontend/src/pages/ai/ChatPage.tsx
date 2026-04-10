import { useState, useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import ChatUI from '../../components/ai/chat/ChatUI';
import type { RichMessage, CrossAgentAction } from '../../components/ai/chat/ChatUI';
import AgentSelector from '../../components/ai/AgentSelector';
import { checkAgentAccess, getMessages, getPlanStatus, sendMessage, sendMessageBackground, sendMessageStream, subscribeToTaskStream, clearStoredTaskStreamId } from '../../api';
import type { AgentId, PipelineStage, ProgressEvent as ApiProgressEvent } from '../../api';
import { useUiAgents } from '../../context/UiAgentsContext';

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
  const location = useLocation();

  const { activeAgentId, setActiveAgentId } = useUiAgents();

  // For new chats, track whether the user has explicitly picked an agent.
  // When the page is loaded with a conversationId or with location.state
  // carrying an agentId (Phase 1 hand-off), we skip the selector.
  const [agentSelected, setAgentSelected] = useState<boolean>(() => {
    if (propConvId) return true; // existing conversation
    const st = (typeof window !== 'undefined' ? window.history.state?.usr : null) as
      | { agentId?: string }
      | null
      | undefined;
    return Boolean(st?.agentId);
  });

  const [conversationStageOutputs, setConversationStageOutputs] = useState<Record<string, string>>({});

  const loadedForRef = useRef<string | undefined>('__uninitialized__');
  const planPollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const resumeAttemptedPlanIdsRef = useRef<Set<string>>(new Set());

  const upsertExecutionPlaceholder = (opts: {
    messageId?: string;
    agentId: AgentId;
    statusMessage: string;
  }) => {
    setMessages((prev) => {
      const updated = [...prev];
      const msgId = opts.messageId?.trim();
      const idx = msgId
        ? updated.findIndex((m) => m.role === 'assistant' && m.messageId === msgId)
        : -1;
      const payload: RichMessage = {
        role: 'assistant',
        content: '',
        messageId: msgId,
        agentId: opts.agentId,
        pipeline: {
          currentStage: 'thinking' as PipelineStage,
          agentId: opts.agentId,
          stageOutputs: conversationStageOutputs,
          progressEvents: [
            {
              stage: 'thinking',
              type: 'task',
              message: opts.statusMessage,
            } as any,
          ],
          outputFile: undefined,
          error: undefined,
        },
      } as any;
      if (idx >= 0) {
        updated[idx] = {
          ...(updated[idx] as any),
          ...payload,
          // Preserve any existing progress history if present, but ensure latest status is visible.
          pipeline: {
            ...(updated[idx].pipeline ?? payload.pipeline),
            progressEvents: [
              ...((updated[idx].pipeline?.progressEvents ?? []) as any[]),
              ...(payload.pipeline?.progressEvents ?? []),
            ],
            currentStage: 'thinking' as PipelineStage,
          },
        } as any;
        return updated;
      }
      updated.push(payload);
      return updated;
    });
  };

  const pushBackgroundStatus = (
    message: string,
    stage: PipelineStage | 'error' = 'thinking',
    planId?: string,
  ) => {
    console.log('[bg] ui-status', { message, stage });
    setMessages((prev) => {
      const updated = [...prev];
      const last = updated[updated.length - 1];
      if (last?.role === 'assistant') {
        const statusText = stage === 'error' ? `⚠️ ${message}` : `_${message}_`;
        updated[updated.length - 1] = {
          ...last,
          // Ensure status is visible even when assistant content is otherwise empty.
          content: last.content?.trim() ? last.content : statusText,
          planId: planId ?? (last as any).planId,
          pipeline: {
            currentStage: (stage === 'error' ? 'thinking' : stage) as PipelineStage,
            agentId: last.agentId ?? activeAgentId,
            stageOutputs: last.pipeline?.stageOutputs ?? conversationStageOutputs,
            progressEvents: [
              ...(last.pipeline?.progressEvents ?? []),
              {
                stage: stage === 'error' ? 'error' : stage,
                type: 'task',
                message,
              } as any,
            ],
            outputFile: last.pipeline?.outputFile,
            error: stage === 'error' ? message : undefined,
          },
        } as any;
      }
      return updated;
    });
  };

  // Re-open Approve/Cancel options on a plan card after failure/cancellation.
  const reopenPlanOptions = (planId: string) => {
    setMessages((prev) => {
      const u = [...prev];
      const idx = u.findIndex((m) => (m as any).planId === planId);
      if (idx >= 0) {
        u[idx] = { ...u[idx], options: ['Approve', 'Cancel'] } as any;
        if (u[idx + 1]?.role === 'user') {
          const t = (u[idx + 1].content || '').trim().toLowerCase();
          if (t === 'approve' || t === 'cancel' || t === 'retry') u.splice(idx + 1, 1);
        }
        if (u[idx + 1]?.role === 'assistant' && !(u[idx + 1].content || '').trim()) {
          u.splice(idx + 1, 1);
        }
      }
      return u;
    });
  };

  useEffect(() => {
    return () => {
      if (planPollIntervalRef.current) {
        clearInterval(planPollIntervalRef.current);
        planPollIntervalRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (loadedForRef.current === propConvId) return;
    loadedForRef.current = propConvId;

    setInitLoading(true);
    setMessages([]);
    setConversationStageOutputs({});
    setConversationId(propConvId);

    // `/new` should always be a blank slate. Do NOT auto-load the latest
    // conversation when no conversationId is provided.
    if (!propConvId) {
      // Check if location.state carries an agentId (Phase 1 hand-off).
      const st = location.state as { agentId?: string } | null | undefined;
      setAgentSelected(Boolean(st?.agentId));
      setInitLoading(false);
      return;
    }

    getMessages(propConvId)
      .then((data) => {
        console.log('[bg] getMessages resolved', {
          conversationId: data.conversationId,
          messageCount: (data.messages ?? []).length,
          agentId: data.agentId,
        });
        const loadedAgentId = (data.agentId ?? activeAgentId) as AgentId;
        const mapped = (data.messages ?? []).map((m) => {
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
          });
        setMessages(mapped);
        if (data.conversationId) setConversationId(data.conversationId);
        if (data.lastStageOutputs) setConversationStageOutputs(data.lastStageOutputs);
        // Sync active agent to match the conversation's stored agentId.
        if (data.agentId) setActiveAgentId(data.agentId as AgentId);

        // Playbook-step resume: if the last message is a playbook step, subscribe to its stream.
        const lastMappedMsg = mapped[mapped.length - 1];
        if (
          lastMappedMsg?.role === 'assistant' &&
          (lastMappedMsg as any).journeyStep === 'playbook'
        ) {
          const playbookStreamId = ((lastMappedMsg as any).streamId || (lastMappedMsg as any).journeySelections?.streamId) as string | undefined;
          const playbookWebsiteUrl = (lastMappedMsg as any).journeySelections?.websiteUrl as string | undefined;
          const streamStatus = (lastMappedMsg as any).streamStatus as string | undefined;
          // Only subscribe if stream is running (not error/cancelled)
          if (playbookStreamId && streamStatus !== 'error' && streamStatus !== 'cancelled' && streamStatus !== 'failed') {
            setMessages((prev) => [...prev, { role: 'assistant', content: '', agentId: loadedAgentId } as any]);
            const handlePlaybookError = (msg: string) => {
              setMessages((prev) => {
                const updated = [...prev];
                // Remove the streaming placeholder
                updated.pop();
                // Update the original playbook message with error + retry option
                const idx = [...updated].reverse().findIndex(
                  (m) => m.role === 'assistant' && (m as any).journeyStep === 'playbook'
                );
                const playbookIdx = idx >= 0 ? updated.length - 1 - idx : -1;
                if (playbookIdx >= 0) {
                  updated[playbookIdx] = {
                    ...updated[playbookIdx],
                    content: `⚠️ Playbook generation failed${msg ? `: ${msg}` : ''}. Click **Retry Playbook** to try again.`,
                    options: ['Retry Playbook'],
                  } as any;
                }
                return updated;
              });
            };
            subscribeToTaskStream(playbookStreamId, {
              onToken: (token) => {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last?.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, content: ((last.content ?? '') + token).replace(/---SECTION:[a-z_]+---\n?/g, '') } as any;
                  }
                  return updated;
                });
              },
              onDone: (doneData) => {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last?.role === 'assistant') {
                    const playbookData = {
                      playbook: String(doneData.playbook ?? last.content ?? ''),
                      websiteAudit: String(doneData.website_audit ?? ''),
                      contextBrief: String(doneData.context_brief ?? ''),
                      icpCard: String(doneData.icp_card ?? ''),
                    };
                    const crossAgentActions: CrossAgentAction[] = [];
                    if (playbookWebsiteUrl) {
                      crossAgentActions.push({
                        label: 'Do Deep Analysis',
                        icon: '🔬',
                        agentId: 'research-orchestrator',
                        initialMessage: `Do deep analysis of ${playbookWebsiteUrl}`,
                      });
                    }
                    updated[updated.length - 1] = {
                      ...last,
                      kind: 'final',
                      playbookData,
                      ...(crossAgentActions.length ? { crossAgentActions } : {}),
                    } as any;
                  }
                  return updated;
                });
              },
              onError: (msg) => handlePlaybookError(msg),
            }).catch((err) => {
              handlePlaybookError(err instanceof Error ? err.message : 'Stream unavailable');
            });
          }
        }

        // Refresh-resume: if latest plan is still executing, show running state and keep polling.
        const latestPlan = [...mapped]
          .reverse()
          .find((m) => m.role === 'assistant' && Boolean((m as any).planId)) as (RichMessage & { planId?: string }) | undefined;
        console.log('[bg] latestPlan candidate', {
          latestPlanId: latestPlan?.planId,
          conversationId: data.conversationId,
        });
        if (latestPlan?.planId && data.conversationId) {
          void getPlanStatus(latestPlan.planId).then(({ status, runningTaskRefFound, errorMessage }) => {
            const planIdx = mapped.findIndex((m) => (m as any).planId === latestPlan.planId);
            const hasExecutionAssistant =
              planIdx >= 0 &&
              mapped.slice(planIdx + 1).some((m) => m.role === 'assistant' && (m.content || '').trim() !== '');
            console.log('[bg] resume-check', {
              planId: latestPlan.planId,
              status,
              runningTaskRefFound,
              hasExecutionAssistant,
              resumeAttempted: resumeAttemptedPlanIdsRef.current.has(latestPlan.planId || ''),
            });

            if (status === 'error' || status === 'interrupted') {
              const errMsg = status === 'interrupted'
                ? (errorMessage || 'Process was interrupted (server restart). You can retry this plan.')
                : (errorMessage || 'Background task failed');
              pushBackgroundStatus(errMsg, 'error', latestPlan.planId);
              setMessages((prev) => {
                const u = [...prev];
                const idx = u.findIndex((m) => (m as any).planId === latestPlan.planId);
                if (idx >= 0) {
                  // Re-open actions on the plan card.
                  u[idx] = { ...(u[idx] as any), options: ['Approve', 'Cancel'] };
                  // Remove stale trailing approve + empty execution assistant, if present.
                  if (u[idx + 1]?.role === 'user') {
                    const next = (u[idx + 1].content || '').trim().toLowerCase();
                    if (next === 'approve' || next === 'cancel') {
                      u.splice(idx + 1, 1);
                    }
                  }
                  if (u[idx + 1]?.role === 'assistant' && !(u[idx + 1].content || '').trim()) {
                    u.splice(idx + 1, 1);
                  }
                }
                return u;
              });
              return;
            }

            // Stale state: DB says executing but no task reference is alive.
            // Unconditionally attempt resume once per plan on this page load.

            if (status === 'executing' && !runningTaskRefFound && !resumeAttemptedPlanIdsRef.current.has(latestPlan.planId!)) {
              resumeAttemptedPlanIdsRef.current.add(latestPlan.planId!);
              console.log('[bg] attempting resume', {
                planId: latestPlan.planId,
                conversationId: data.conversationId,
                agentId: loadedAgentId,
              });
              // Actually await the sendMessageBackground to ensure it runs
              (async () => {
                try {
                  const resumeResult = await sendMessageBackground({
                    message: 'approve',
                    conversationId: data.conversationId,
                    agentId: loadedAgentId,
                    planId: latestPlan.planId,
                  });
                  console.log('[bg] resume sendMessageBackground result', resumeResult);

                  // If taskStream is returned, subscribe to it
                  if (resumeResult.backgroundExecution && resumeResult.taskStream?.streamId) {
                    const streamId = resumeResult.taskStream.streamId;
                    console.log('[bg] resume: subscribing to task stream', { streamId });
                    await subscribeToTaskStream(streamId, {
                      onToken: (token) => {
                        setMessages((prev) => {
                          const updated = [...prev];
                          const last = updated[updated.length - 1];
                          if (last?.role === 'assistant') {
                            updated[updated.length - 1] = { ...last, content: ((last.content ?? '') + token).replace(/---SECTION:[a-z_]+---\n?/g, '') };
                          }
                          return updated;
                        });
                      },
                      onDone: async () => {
                        console.log('[bg] resume task stream done');
                        const refreshed = await getMessages(data.conversationId);
                        const a = (refreshed.agentId ?? loadedAgentId) as AgentId;
                        setMessages((refreshed.messages ?? []).map((m) => ({ ...m, agentId: a } as any)));
                        if (refreshed.lastStageOutputs) setConversationStageOutputs(refreshed.lastStageOutputs);
                      },
                      onError: async (msg) => {
                        console.error('[bg] resume task stream error:', msg);
                        pushBackgroundStatus(`Background task failed: ${msg}`, 'error', latestPlan.planId);
                        if (latestPlan.planId) reopenPlanOptions(latestPlan.planId);
                      },
                    });
                  }
                } catch (err) {
                  console.error('[bg] resume failed', err);
                  try {
                    await sendMessageBackground({
                      message: 'cancel',
                      conversationId: data.conversationId,
                      agentId: loadedAgentId,
                      planId: latestPlan.planId,
                    });
                  } catch (cancelErr) {
                    console.error('[bg] cancel after resume failed also failed', cancelErr);
                  }
                  setMessages((prev) => {
                    const u = [...prev];
                    const idx = u.findIndex((m) => (m as any).planId === latestPlan.planId);
                    if (idx >= 0) {
                      u[idx] = { ...(u[idx] as any), options: ['Approve', 'Cancel'] };
                      if (u[idx + 1]?.role === 'user') {
                        const next = (u[idx + 1].content || '').trim().toLowerCase();
                        if (next === 'approve' || next === 'cancel') u.splice(idx + 1, 1);
                      }
                    }
                    return u;
                  });
                }
              })();
            }

            if (status === 'executing' && !hasExecutionAssistant) {
              return;
            }

            if (status !== 'executing') return;
            const executionAssistantMsg =
              planIdx >= 0
                ? mapped.slice(planIdx + 1).find((m) => m.role === 'assistant' && Boolean(m.messageId))
                : undefined;
            upsertExecutionPlaceholder({
              messageId: executionAssistantMsg?.messageId,
              agentId: loadedAgentId,
              statusMessage: 'Background task running — you can refresh and it will continue.',
            });
            if (planPollIntervalRef.current) {
              clearInterval(planPollIntervalRef.current);
              planPollIntervalRef.current = null;
            }
            const pollOnce = async () => {
              try {
                const st = await getPlanStatus(latestPlan.planId!);
                console.log('[bg] poll-status (resume path)', {
                  planId: latestPlan.planId,
                  status: st.status,
                  runningTaskRefFound: st.runningTaskRefFound,
                });
                if (st.status === 'executing') {
                  pushBackgroundStatus(
                    st.runningTaskRefFound
                      ? 'Background task running'
                      : 'Background task reference missing, trying to resume...',
                    'thinking',
                  );
                  return;
                }
                if (st.status === 'error' || st.status === 'interrupted') {
                  pushBackgroundStatus(st.errorMessage ? `Background task failed: ${st.errorMessage}` : 'Background task failed', 'error', latestPlan.planId);
                }
                if (st.status === 'cancelled') {
                  pushBackgroundStatus('Background task cancelled', 'error', latestPlan.planId);
                }
                if (st.status !== 'done' && st.status !== 'error' && st.status !== 'cancelled' && st.status !== 'interrupted') return;
                if (planPollIntervalRef.current) {
                  clearInterval(planPollIntervalRef.current);
                  planPollIntervalRef.current = null;
                }
                const refreshed = await getMessages(data.conversationId);
                const a = (refreshed.agentId ?? loadedAgentId) as AgentId;
                setMessages((refreshed.messages ?? []).map((m) => ({ ...m, agentId: a } as any)));
                if (refreshed.lastStageOutputs) setConversationStageOutputs(refreshed.lastStageOutputs);
                if ((st.status === 'error' || st.status === 'cancelled' || st.status === 'interrupted') && latestPlan.planId) {
                  reopenPlanOptions(latestPlan.planId);
                }
              } catch {
                // retry later
              }
            };
            planPollIntervalRef.current = setInterval(() => void pollOnce(), 2500);
            void pollOnce();
          });
        }
      })
      .catch(() => setMessages([]))
      .finally(() => setInitLoading(false));
  }, [propConvId, activeAgentId]);

  const runStream = async (
    userMessage: string,
    _retryFromStage?: PipelineStage,
    _retryStageOutputs?: Record<string, string>,
    streamAgentId?: AgentId
  ) => {
    const agent = streamAgentId ?? activeAgentId;
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
    setMessages((prev) => [...prev, { role: 'assistant', content: '', agentId: agent }]);

    try {
      // Plan-only: every user message generates a plan. Execution happens ONLY via approve API.
      const plan = await sendMessageStream({
        message: userMessage,
        conversationId,
        agentId: agent,
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
                    agentId: agent,
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
                    agentId: agent,
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
          onToken: (token) => {
            setMessages((prev) => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = {
                  ...last,
                  content: ((last.content ?? '') + token).replace(/---SECTION:[a-z_]+---\n?/g, ''),
                } as any;
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

      // Journey free-text: stream returned mode=journey, refresh messages from DB.
      if (plan.mode === 'journey') {
        const cid = plan.conversationId || conversationId;
        if (cid) {
          const data = await getMessages(cid);
          const loadedAgentId = (data.agentId ?? agent) as AgentId;
          const loaded = (data.messages ?? []).map((m) => ({ ...m, agentId: loadedAgentId } as any));
          setMessages(loaded);

          // If last message is playbook step, subscribe to task stream.
          const lastLoaded = loaded[loaded.length - 1];
          if (lastLoaded?.role === 'assistant' && (lastLoaded as any).journeyStep === 'playbook') {
            const streamId = ((lastLoaded as any).streamId || (lastLoaded as any).journeySelections?.streamId) as string | undefined;
            const websiteUrl = (lastLoaded as any).journeySelections?.websiteUrl as string | undefined;
            const streamStatus = (lastLoaded as any).streamStatus as string | undefined;
            // Only subscribe if stream is running (not error/cancelled)
            if (streamId && streamStatus !== 'error' && streamStatus !== 'cancelled' && streamStatus !== 'failed') {
              setMessages((prev) => [
                ...prev,
                { role: 'assistant', content: '', agentId: loadedAgentId } as any,
              ]);
              try {
                await subscribeToTaskStream(streamId, {
                  onToken: (token) => {
                    setMessages((prev) => {
                      const updated = [...prev];
                      const last = updated[updated.length - 1];
                      if (last?.role === 'assistant') {
                        updated[updated.length - 1] = { ...last, content: ((last.content ?? '') + token).replace(/---SECTION:[a-z_]+---\n?/g, '') } as any;
                      }
                      return updated;
                    });
                  },
                  onDone: (doneData) => {
                    setMessages((prev) => {
                      const updated = [...prev];
                      const last = updated[updated.length - 1];
                      if (last?.role === 'assistant') {
                        const playbookData = {
                          playbook: String(doneData.playbook ?? last.content ?? ''),
                          websiteAudit: String(doneData.website_audit ?? ''),
                          contextBrief: String(doneData.context_brief ?? ''),
                          icpCard: String(doneData.icp_card ?? ''),
                        };
                        const crossAgentActions: CrossAgentAction[] = [];
                        if (websiteUrl) {
                          crossAgentActions.push({
                            label: 'Do Deep Analysis',
                            icon: '🔬',
                            agentId: 'research-orchestrator',
                            initialMessage: `Do deep analysis of ${websiteUrl}`,
                          });
                        }
                        updated[updated.length - 1] = {
                          ...last,
                          kind: 'final',
                          playbookData,
                          ...(crossAgentActions.length ? { crossAgentActions } : {}),
                        } as any;
                      }
                      return updated;
                    });
                  },
                  onError: (msg) => {
                    setMessages((prev) => {
                      const updated = [...prev];
                      const last = updated[updated.length - 1];
                      if (last?.role === 'assistant') {
                        updated[updated.length - 1] = { ...last, content: last.content || `⚠️ ${msg}` } as any;
                      }
                      return updated;
                    });
                  },
                });
              } catch (streamErr) {
                const msg = streamErr instanceof Error ? streamErr.message : 'Playbook stream error';
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last?.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, content: last.content || `⚠️ ${msg}` } as any;
                  }
                  return updated;
                });
              }
            }
          }
        }
        return;
      }

      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.role === 'assistant') {
          const isPlanResponse = Boolean(plan.planId || plan.planMarkdown);
          updated[updated.length - 1] = {
            ...last,
            // If tokens were streamed, preserve them; otherwise fall back to full markdown.
            content: (last.content ?? '').trim() ? last.content : (plan.planMarkdown ?? ''),
            kind: isPlanResponse ? 'plan' : 'final',
            planId: isPlanResponse ? plan.planId : undefined,
            messageId: plan.planMessageId ?? last.messageId,
            options: isPlanResponse ? ['Approve', 'Cancel'] : undefined,
            pipeline: {
              currentStage: 'done',
              agentId: agent,
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

  const runStreamRef = useRef(runStream);
  runStreamRef.current = runStream;

  /**
   * Cross-agent action: check plan access, then navigate to a new conversation
   * with the specified agent and an initial message.
   */
  const handleCrossAgentAction = async (action: CrossAgentAction) => {
    try {
      const access = await checkAgentAccess(action.agentId);
      if (!access.allowed) {
        // Redirect to payment page with context
        navigate('/payment', {
          state: {
            reason: access.reason || 'A paid plan is required to use this feature.',
            requiredPlanSlug: access.required_plan_slug,
            requiredPlanName: access.required_plan_name,
            requiredPlanPrice: access.required_plan_price,
            returnTo: '/new',
            returnState: { agentId: action.agentId, initialMessage: action.initialMessage },
          },
        });
        return;
      }
    } catch {
      // If access check fails (network etc.), let the backend enforce on the stream call
    }
    navigate('/new', {
      state: { agentId: action.agentId, initialMessage: action.initialMessage },
    });
  };

  const phase1AutoSendKeysRef = useRef<Set<string>>(new Set());

  /**
   * Phase 1 handoff: `/new` may carry `agentId` and/or `initialMessage`.
   * - With message: select agent, clear state, auto-run plan stream.
   * - Agent only: select agent, clear state; user composes the first message in Phase 2.
   */
  useEffect(() => {
    if (initLoading) return;
    const st = location.state as { initialMessage?: string; agentId?: AgentId } | null | undefined;
    const msg = typeof st?.initialMessage === 'string' ? st.initialMessage.trim() : '';
    const hasAgent = Boolean(st?.agentId);
    if ((!msg && !hasAgent) || phase1AutoSendKeysRef.current.has(location.key)) return;
    phase1AutoSendKeysRef.current.add(location.key);
    if (st?.agentId) setActiveAgentId(st.agentId);
    setAgentSelected(true);
    // Clear existing conversation to start fresh when triggered by cross-agent action
    setMessages([]);
    setConversationId(undefined);
    setConversationStageOutputs({});
    navigate(location.pathname, { replace: true, state: {} });
    if (msg) void runStreamRef.current(msg, undefined, undefined, st?.agentId);
  }, [initLoading, location.key, location.pathname, location.state, navigate, setActiveAgentId]);

  const handleOptionSelect = async (option: string) => {
    if (!conversationId) return;
    setLoading(true);
    try {
      setMessages((prev) => [...prev, { role: 'user', content: option } as any]);
      // Approve/Retry: start durable background execution via /message/background.
      const optionLower = option.trim().toLowerCase();
      if (optionLower === 'approve' || optionLower === 'retry') {
        // Clear any stale stream IDs from localStorage before starting fresh
        clearStoredTaskStreamId('plan/execute', { onboardingId: null, userId: null });
        
        let retryPlanId: string | undefined;
        if (optionLower === 'retry') {
          const latestPlan = [...messages]
            .reverse()
            .find((m) => m.role === 'assistant' && Boolean((m as any).planId)) as
            | (RichMessage & { planId?: string })
            | undefined;
          retryPlanId = latestPlan?.planId;
        }
        const ack = await sendMessageBackground({
          message: 'approve',
          conversationId,
          agentId: activeAgentId,
          planId: retryPlanId,
        });
        const cid = ack.conversationId || conversationId;
        const pid = ack.planId;

        // Use task stream if available (preferred path)
        if (ack.taskStream?.streamId && pid && cid) {
          const streamId = ack.taskStream.streamId;
          console.log('[bg] Starting task stream for plan execution', { streamId, planId: pid });

          // Add a placeholder assistant message for the streaming content
          setMessages((prev) => [...prev, { role: 'assistant', content: '', agentId: activeAgentId, planId: pid } as any]);

          try {
            await subscribeToTaskStream(streamId, {
              onToken: (token) => {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last?.role === 'assistant') {
                    updated[updated.length - 1] = { ...last, content: ((last.content ?? '') + token).replace(/---SECTION:[a-z_]+---\n?/g, '') };
                  }
                  return updated;
                });
              },
              onStage: (stage, label) => {
                console.log('[bg] Stage:', stage, label);
                pushBackgroundStatus(label || `Stage: ${stage}`, stage as any, pid);
              },
              onProgress: (data) => {
                console.log('[bg] Progress:', data);
              },
              onDone: async () => {
                console.log('[bg] Task stream done');
                // Reload messages from backend to get final state
                const data = await getMessages(cid);
                const loadedAgentId = (data.agentId ?? activeAgentId) as AgentId;
                setMessages((data.messages ?? []).map((m) => ({ ...m, agentId: loadedAgentId } as any)));
                if (data.conversationId) setConversationId(data.conversationId);
                if (data.lastStageOutputs) setConversationStageOutputs(data.lastStageOutputs);
              },
              onError: async (msg) => {
                console.error('[bg] Task stream error:', msg);
                pushBackgroundStatus(`Background task failed: ${msg}`, 'error', pid);
                reopenPlanOptions(pid);
                // Reload messages from backend
                const data = await getMessages(cid);
                const loadedAgentId = (data.agentId ?? activeAgentId) as AgentId;
                setMessages((data.messages ?? []).map((m) => ({ ...m, agentId: loadedAgentId } as any)));
              },
            });
          } catch (err) {
            console.error('[bg] Task stream subscription failed:', err);
            pushBackgroundStatus(`Background task failed: ${err instanceof Error ? err.message : 'Unknown error'}`, 'error', pid);
            reopenPlanOptions(pid);
          }
          return;
        }

        // Fallback to polling if no task stream (legacy path)
        if (pid && cid) {
          console.log('[bg] Falling back to polling (no taskStream in response)');
          upsertExecutionPlaceholder({
            messageId: ack.assistantMessageId,
            agentId: activeAgentId,
            statusMessage: 'Background task running — you can refresh and it will continue.',
          });
          pushBackgroundStatus('Background task running', 'thinking', pid);
          if (planPollIntervalRef.current) {
            clearInterval(planPollIntervalRef.current);
            planPollIntervalRef.current = null;
          }
          const pollOnce = async () => {
            try {
              const st = await getPlanStatus(pid);
              console.log('[bg] poll-status (approve path)', {
                planId: pid,
                status: st.status,
                runningTaskRefFound: st.runningTaskRefFound,
              });
              if (st.status === 'executing') {
                pushBackgroundStatus(
                  st.runningTaskRefFound
                    ? 'Background task running'
                    : 'Background task reference missing, waiting for resume...',
                  'thinking',
                );
                return;
              }
              if (st.status === 'error' || st.status === 'interrupted') {
                pushBackgroundStatus(st.errorMessage ? `Background task failed: ${st.errorMessage}` : 'Background task failed', 'error', pid);
              }
              if (st.status === 'cancelled') {
                pushBackgroundStatus('Background task cancelled', 'error', pid);
              }
              if (st.status !== 'done' && st.status !== 'error' && st.status !== 'cancelled' && st.status !== 'interrupted') return;
              if (planPollIntervalRef.current) {
                clearInterval(planPollIntervalRef.current);
                planPollIntervalRef.current = null;
              }
              const data = await getMessages(cid);
              const loadedAgentId = (data.agentId ?? activeAgentId) as AgentId;
              setMessages((data.messages ?? []).map((m) => ({ ...m, agentId: loadedAgentId } as any)));
              if (data.conversationId) setConversationId(data.conversationId);
              if (data.lastStageOutputs) setConversationStageOutputs(data.lastStageOutputs);
              if (st.status === 'error' || st.status === 'cancelled' || st.status === 'interrupted') reopenPlanOptions(pid);
            } catch {
              // retry
            }
          };
          planPollIntervalRef.current = setInterval(() => void pollOnce(), 2500);
          void pollOnce();
        }
        return;
      }

      const ack = await sendMessage({ message: option, conversationId, agentId: activeAgentId });
      if (ack.conversationId) setConversationId(ack.conversationId);

      if (ack.mode === 'journey') {
        const cid = ack.conversationId || conversationId;
        if (cid) {
          const data = await getMessages(cid);
          const loadedAgentId = (data.agentId ?? activeAgentId) as AgentId;
          const loaded = (data.messages ?? []).map((m) => ({ ...m, agentId: loadedAgentId } as any));
          setMessages(loaded);

          // If the last assistant message is the playbook step, subscribe to the task stream.
          const lastLoaded = loaded[loaded.length - 1];
          if (
            lastLoaded?.role === 'assistant' &&
            (lastLoaded as any).journeyStep === 'playbook'
          ) {
            const streamId = ((lastLoaded as any).streamId || (lastLoaded as any).journeySelections?.streamId) as string | undefined;
            const websiteUrl2 = (lastLoaded as any).journeySelections?.websiteUrl as string | undefined;
            const streamStatus = (lastLoaded as any).streamStatus as string | undefined;
            // Only subscribe if stream is running (not error/cancelled)
            if (streamId && streamStatus !== 'error' && streamStatus !== 'cancelled' && streamStatus !== 'failed') {
              setLoading(true);
              // Append a streaming assistant message.
              setMessages((prev) => [
                ...prev,
                { role: 'assistant', content: '', agentId: loadedAgentId } as any,
              ]);
              try {
                await subscribeToTaskStream(streamId, {
                  onToken: (token) => {
                    setMessages((prev) => {
                      const updated = [...prev];
                      const last = updated[updated.length - 1];
                      if (last?.role === 'assistant') {
                        updated[updated.length - 1] = {
                          ...last,
                          content: ((last.content ?? '') + token).replace(/---SECTION:[a-z_]+---\n?/g, ''),
                        } as any;
                      }
                      return updated;
                    });
                  },
                  onDone: (doneData) => {
                    setMessages((prev) => {
                      const updated = [...prev];
                      const last = updated[updated.length - 1];
                      if (last?.role === 'assistant') {
                        const playbookData = {
                          playbook: String(doneData.playbook ?? last.content ?? ''),
                          websiteAudit: String(doneData.website_audit ?? ''),
                          contextBrief: String(doneData.context_brief ?? ''),
                          icpCard: String(doneData.icp_card ?? ''),
                        };
                        const crossAgentActions: CrossAgentAction[] = [];
                        if (websiteUrl2) {
                          crossAgentActions.push({
                            label: 'Do Deep Analysis',
                            icon: '🔬',
                            agentId: 'research-orchestrator',
                            initialMessage: `Do deep analysis of ${websiteUrl2}`,
                          });
                        }
                        updated[updated.length - 1] = {
                          ...last,
                          kind: 'final',
                          playbookData,
                          ...(crossAgentActions.length ? { crossAgentActions } : {}),
                        } as any;
                      }
                      return updated;
                    });
                  },
                  onError: (msg) => {
                    setMessages((prev) => {
                      const updated = [...prev];
                      const last = updated[updated.length - 1];
                      if (last?.role === 'assistant') {
                        updated[updated.length - 1] = {
                          ...last,
                          content: last.content || `⚠️ Playbook generation failed: ${msg}`,
                        } as any;
                      }
                      return updated;
                    });
                  },
                });
              } catch (err) {
                const msg = err instanceof Error ? err.message : 'Playbook stream error';
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last?.role === 'assistant') {
                    updated[updated.length - 1] = {
                      ...last,
                      content: last.content || `⚠️ ${msg}`,
                    } as any;
                  }
                  return updated;
                });
              } finally {
                setLoading(false);
              }
            }
          }
        }
        return;
      }

      if (ack.status === 'cancelled') {
        setMessages((prev) => [...prev, { role: 'assistant', content: 'Plan cancelled.' } as any]);
        return;
      }
      console.log('ack', ack);

      // New path: use task stream for background execution when taskStream metadata is present
      if (ack.backgroundExecution && ack.taskStream?.streamId) {
        const cid = ack.conversationId || conversationId;
        const pid = ack.planId;
        const streamId = ack.taskStream.streamId;
        console.log('[bg] Starting task stream subscription', { streamId, planId: pid });

        // Add a placeholder assistant message for the streaming content
        setMessages((prev) => [...prev, { role: 'assistant', content: '', agentId: activeAgentId } as any]);

        try {
          await subscribeToTaskStream(streamId, {
            onToken: (token) => {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.role === 'assistant') {
                  updated[updated.length - 1] = { ...last, content: ((last.content ?? '') + token).replace(/---SECTION:[a-z_]+---\n?/g, '') };
                }
                return updated;
              });
            },
            onStage: (stage, label) => {
              console.log('[bg] Stage:', stage, label);
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
            onProgress: (data) => {
              console.log('[bg] Progress:', data);
            },
            onDone: async () => {
              console.log('[bg] Task stream done');
              // Reload messages from backend to get final state
              if (cid) {
                const data = await getMessages(cid);
                const loadedAgentId = (data.agentId ?? activeAgentId) as AgentId;
                setMessages((data.messages ?? []).map((m) => ({ ...m, agentId: loadedAgentId } as any)));
                if (data.conversationId) setConversationId(data.conversationId);
                if (data.lastStageOutputs) setConversationStageOutputs(data.lastStageOutputs);
              }
            },
            onError: async (msg) => {
              console.error('[bg] Task stream error:', msg);
              pushBackgroundStatus(`Background task failed: ${msg}`, 'error', pid);
              if (pid) reopenPlanOptions(pid);
              // Reload messages from backend
              if (cid) {
                const data = await getMessages(cid);
                const loadedAgentId = (data.agentId ?? activeAgentId) as AgentId;
                setMessages((data.messages ?? []).map((m) => ({ ...m, agentId: loadedAgentId } as any)));
              }
            },
          });
        } catch (err) {
          console.error('[bg] Task stream subscription failed:', err);
          pushBackgroundStatus(`Background task failed: ${err instanceof Error ? err.message : 'Unknown error'}`, 'error', pid);
          if (pid) reopenPlanOptions(pid);
        }
        return;
      }

      // Legacy background path (kept for non-stream callers): still poll plan completion only.
      if (ack.backgroundExecution && ack.planId) {
        if (planPollIntervalRef.current) {
          clearInterval(planPollIntervalRef.current);
          planPollIntervalRef.current = null;
        }
        const cid = ack.conversationId || conversationId;
        const pid = ack.planId;
        const pollOnce = async () => {
          try {
            const st = await getPlanStatus(pid);
            console.log('[bg] poll-status (legacy path)', {
              planId: pid,
              status: st.status,
              runningTaskRefFound: st.runningTaskRefFound,
            });
            if (st.status === 'executing') {
              pushBackgroundStatus('Background task running', 'thinking');
              return;
            }
            if (st.status === 'error' || st.status === 'interrupted') {
              pushBackgroundStatus(st.errorMessage ? `Background task failed: ${st.errorMessage}` : 'Background task failed', 'error', pid);
            }
            if (st.status === 'cancelled') {
              pushBackgroundStatus('Background task cancelled', 'error', pid);
            }
            if (st.status !== 'done' && st.status !== 'error' && st.status !== 'cancelled' && st.status !== 'interrupted') return;
            if (planPollIntervalRef.current) {
              clearInterval(planPollIntervalRef.current);
              planPollIntervalRef.current = null;
            }
            const data = await getMessages(cid);
            const loadedAgentId = (data.agentId ?? activeAgentId) as AgentId;
            setMessages((data.messages ?? []).map((m) => ({ ...m, agentId: loadedAgentId } as any)));
            if (data.conversationId) setConversationId(data.conversationId);
            if (data.lastStageOutputs) setConversationStageOutputs(data.lastStageOutputs);
            if (st.status === 'error' || st.status === 'cancelled' || st.status === 'interrupted') reopenPlanOptions(pid);
          } catch {
            // retry
          }
        };
        planPollIntervalRef.current = setInterval(() => void pollOnce(), 2500);
        void pollOnce();
        return;
      }

      if (ack.requiresStream) {
        setMessages((prev) => [...prev, { role: 'assistant', content: '', agentId: activeAgentId } as any]);
        const result = await sendMessageStream({
          message: option,
          conversationId: ack.conversationId || conversationId,
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
                  updated[updated.length - 1] = { ...last, content: ((last.content ?? '') + token).replace(/---SECTION:[a-z_]+---\n?/g, '') };
                }
                return updated;
              });
            },
          },
        });
        if (result.conversationId) setConversationId(result.conversationId);
        if (result.model) setModel(result.model);
        if (result.stageOutputs) setConversationStageOutputs((prev) => ({ ...prev, ...result.stageOutputs }));
      }
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

  // New chat without an agent selected → show agent selection screen
  if (!propConvId && !agentSelected && messages.length === 0) {
    return (
      <AgentSelector
        onSelect={(agentId) => {
          setActiveAgentId(agentId);
          setAgentSelected(true);
        }}
      />
    );
  }

  return (
    <ChatUI
      messages={messages}
      onSend={handleSend}
      onOptionSelect={handleOptionSelect}
      onCrossAgentAction={handleCrossAgentAction}
      loading={loading}
      agentId={activeAgentId}
      subtitle={model ? `${activeAgentId} · ${model}` : undefined}
      retryHandlers={retryHandlers}
    />
  );
}
