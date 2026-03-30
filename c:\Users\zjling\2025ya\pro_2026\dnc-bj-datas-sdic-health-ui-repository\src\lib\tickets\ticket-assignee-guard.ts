import type { Sql } from "postgres";

export type AssigneeGuardFailureCode = "NO_GROUPS_ASSIGNED" | "AGENT_OFFLINE" | "GROUP_NOT_ALLOWED";

export type AssigneeGuardResult =
  | { ok: true }
  | { ok: false; code: AssigneeGuardFailureCode; message: string };

/**
 * Validates assigning a unified ticket to an agent: queue groups + online session.
 */
export async function assertTicketAssigneeAllowed(
  sql: Sql,
  assigneeUserId: number,
  ticketGroupId: number | null | undefined
): Promise<AssigneeGuardResult> {
  const profileRows = (await sql`
    SELECT current_status, is_online
    FROM public.agent_profiles
    WHERE user_id = ${assigneeUserId}
    LIMIT 1
  `) as { current_status?: string; is_online?: boolean }[];

  const status = profileRows[0]?.current_status ?? "offline";
  const online = profileRows[0]?.is_online === true;

  if (status === "offline" || !online) {
    return {
      ok: false,
      code: "AGENT_OFFLINE",
      message: "Agent is offline; assignment is not allowed.",
    };
  }

  const rowRows = (await sql`
    SELECT primary_group_ids, secondary_group_ids
    FROM public.ticket_agent_queue_assignments
    WHERE system_user_id = ${assigneeUserId}
    LIMIT 1
  `) as { primary_group_ids?: unknown; secondary_group_ids?: unknown }[];

  const primary = normalizeBigIntArray(rowRows[0]?.primary_group_ids);
  const secondary = normalizeBigIntArray(rowRows[0]?.secondary_group_ids);
  const allowed = new Set([...primary, ...secondary]);

  if (allowed.size === 0) {
    return {
      ok: false,
      code: "NO_GROUPS_ASSIGNED",
      message: "No Group assigned to the User",
    };
  }

  if (ticketGroupId != null && Number.isFinite(Number(ticketGroupId))) {
    const gid = Number(ticketGroupId);
    if (!allowed.has(gid)) {
      return {
        ok: false,
        code: "GROUP_NOT_ALLOWED",
        message: "This agent is not assigned to the ticket's group (primary or secondary).",
      };
    }
  }

  return { ok: true };
}

function normalizeBigIntArray(v: unknown): number[] {
  if (v == null) return [];
  if (!Array.isArray(v)) return [];
  return v.map((x) => Number(x)).filter((n) => Number.isFinite(n));
}
