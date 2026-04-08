/**
 * Plan Execution via Task Stream
 *
 * This module provides helper functions for handling plan execution through
 * the task-stream system. When a message triggers plan approval, the backend
 * returns taskStream metadata which can be used to subscribe to real-time updates.
 *
 * Usage flow:
 * 1. Call sendMessage() or sendMessageBackground() with "approve" message
 * 2. If response contains taskStream, use subscribeToTaskStream() for real-time updates
 * 3. The task stream provides stage, progress, and token events
 * 4. Task is durable and survives page refresh
 */

import { runResumableTaskStream, TaskStreamEvent, clearStoredTaskStreamId, getStoredTaskStreamId, storeTaskStreamId } from './taskStream';
import { getUserIdFromJwt } from '../authSession';
import { subscribeToTaskStream as coreSubscribeToTaskStream } from './core';

export const PLAN_EXECUTE_TASK_TYPE = 'plan/execute';

export interface PlanExecuteCallbacks {
  onStage?: (stage: string, label: string) => void;
  onProgress?: (event: Record<string, unknown>) => void;
  onToken?: (token: string) => void;
  onDone?: (data: { plan_id: string; conversation_id: string; status: string; assistant_message_id?: string }) => void;
  onError?: (message: string) => void;
}

/**
 * Subscribe to a task stream for real-time plan execution updates.
 * Call this after sendMessage() returns with taskStream metadata.
 *
 * Example:
 * ```ts
 * const result = await sendMessage({ message: 'approve', conversationId, agentId });
 * if (result.taskStream) {
 *   await subscribeToPlanExecutionStream(result.taskStream.streamId, callbacks);
 * }
 * ```
 */
export async function subscribeToPlanExecutionStream(
  streamId: string,
  callbacks: PlanExecuteCallbacks,
): Promise<void> {
  // Store the stream ID so it can be resumed after page refresh
  const userId = getUserIdFromJwt();
  storeTaskStreamId(PLAN_EXECUTE_TASK_TYPE, streamId, {
    userId,
  });

  await coreSubscribeToTaskStream(streamId, {
    onStage: callbacks.onStage,
    onToken: callbacks.onToken,
    onProgress: callbacks.onProgress,
    onDone: (data) => {
      // Clear stored ID on completion
      clearStoredTaskStreamId(PLAN_EXECUTE_TASK_TYPE, {
        userId,
      });
      callbacks.onDone?.({
        plan_id: String(data.plan_id ?? ''),
        conversation_id: String(data.conversation_id ?? ''),
        status: String(data.status ?? 'complete'),
        assistant_message_id: data.assistant_message_id as string | undefined,
      });
    },
    onError: (message) => {
      // Clear stored ID on error
      clearStoredTaskStreamId(PLAN_EXECUTE_TASK_TYPE, {
        userId,
      });
      callbacks.onError?.(message);
    },
  });
}

/**
 * Check if there's an active plan execution task stream for the current user.
 */
export function hasActivePlanExecution(): boolean {
  const userId = getUserIdFromJwt();
  return Boolean(getStoredTaskStreamId(PLAN_EXECUTE_TASK_TYPE, {
    userId,
  }));
}

/**
 * Clear any stored plan execution stream ID (e.g., after plan completes/errors).
 */
export function clearPlanExecutionStream(): void {
  const userId = getUserIdFromJwt();
  clearStoredTaskStreamId(PLAN_EXECUTE_TASK_TYPE, {
    userId,
  });
}

/**
 * Resume an existing plan execution stream if one exists.
 * Returns true if a stream was found and resumed.
 */
export async function resumePlanExecutionIfExists(callbacks: PlanExecuteCallbacks): Promise<boolean> {
  const userId = getUserIdFromJwt();
  const streamId = getStoredTaskStreamId(PLAN_EXECUTE_TASK_TYPE, {
    userId,
  });

  if (!streamId) {
    return false;
  }

  // Use runResumableTaskStream which handles resume automatically
  await runResumableTaskStream(PLAN_EXECUTE_TASK_TYPE, {
    userId,
    payload: {}, // Not used for resume
    callbacks: {
      onEvent: (event: TaskStreamEvent) => {
        const type = event.type;
        if (type === 'stage') {
          callbacks.onStage?.(String(event.stage ?? ''), String(event.label ?? ''));
        } else if (type === 'progress') {
          callbacks.onProgress?.(event as Record<string, unknown>);
        } else if (type === 'token' && typeof event.token === 'string') {
          callbacks.onToken?.(event.token);
        }
      },
      onDone: (event: TaskStreamEvent) => {
        callbacks.onDone?.({
          plan_id: String(event.plan_id ?? ''),
          conversation_id: String(event.conversation_id ?? ''),
          status: String(event.status ?? 'complete'),
          assistant_message_id: event.assistant_message_id as string | undefined,
        });
      },
      onError: (event: TaskStreamEvent) => {
        callbacks.onError?.(String(event.message ?? 'Plan execution failed'));
      },
    },
  });

  return true;
}
