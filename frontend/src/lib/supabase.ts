import { createClient } from '@supabase/supabase-js';

const supabaseUrl = 'https://bbaydychuoahmdkbgghw.supabase.co';
const supabaseAnonKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJiYXlkeWNodW9haG1ka2JnZ2h3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Njc4ODYyODEsImV4cCI6MjA4MzQ2MjI4MX0.aYalpYYU9I1x30U4KsW5WluyASf5RMAhKjx4JfS41Bo';

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

// ============================================
// LEAD MANAGEMENT FUNCTIONS
// ============================================

/**
 * Save a new lead to Supabase
 * @param {Object} leadData - The lead data to save
 * @returns {Object} - The saved lead or error
 */
export const saveLead = async (leadData) => {
  try {
    const { data, error } = await supabase
      .from('leads')
      .insert([{
        name: leadData.name,
        email: leadData.email,
        domain: leadData.domain,
        subdomain: leadData.subdomain,
        outcome_seeked: leadData.outcomeSeeked,
        individual_type: leadData.individualType,
        persona: leadData.persona,
        nature_of_business: leadData.natureOfBusiness,
        business_website: leadData.businessWebsite,
        manual_business_details: leadData.manualBusinessDetails,
        problem_description: leadData.problemDescription,
        micro_solutions_tried: leadData.microSolutionsTried,
        micro_solutions_details: leadData.microSolutionsDetails,
        tech_competency_level: leadData.techCompetencyLevel,
        timeline_urgency: leadData.timelineUrgency,
        problem_due_to_poor_management: leadData.problemDueToPoorManagement,
        ai_recommendations: leadData.aiRecommendations,
        lead_score: calculateLeadScore(leadData),
        status: 'new'
      }])
      .select();

    if (error) throw error;
    return { success: true, data: data[0] };
  } catch (error) {
    console.error('Error saving lead:', error);
    return { success: false, error: error.message };
  }
};

/**
 * Update an existing lead
 * @param {string} leadId - The lead ID to update
 * @param {Object} updates - The fields to update
 */
export const updateLead = async (leadId, updates) => {
  try {
    const { data, error } = await supabase
      .from('leads')
      .update(updates)
      .eq('id', leadId)
      .select();

    if (error) throw error;
    return { success: true, data: data[0] };
  } catch (error) {
    console.error('Error updating lead:', error);
    return { success: false, error: error.message };
  }
};

/**
 * Get all leads (for admin dashboard)
 * @param {Object} filters - Optional filters
 */
export const getLeads = async (filters = {}) => {
  try {
    let query = supabase
      .from('leads')
      .select('*')
      .order('created_at', { ascending: false });

    // Apply filters
    if (filters.domain) {
      query = query.eq('domain', filters.domain);
    }
    if (filters.status) {
      query = query.eq('status', filters.status);
    }
    if (filters.individualType) {
      query = query.eq('individual_type', filters.individualType);
    }

    const { data, error } = await query;

    if (error) throw error;
    return { success: true, data };
  } catch (error) {
    console.error('Error fetching leads:', error);
    return { success: false, error: error.message };
  }
};

/**
 * Calculate lead score based on various factors
 * Score: 0-100
 */
const calculateLeadScore = (leadData) => {
  let score = 0;

  // Individual type scoring (max 25)
  const typeScores = {
    'founder-owner': 25,
    'sales-marketing': 20,
    'ops-admin': 18,
    'finance-legal': 18,
    'hr-recruiting': 15,
    'support-success': 15,
    'individual-student': 10
  };
  score += typeScores[leadData.individualType] || 10;

  // Tech competency (max 20) - higher = better lead
  score += (leadData.techCompetencyLevel || 3) * 4;

  // Timeline urgency (max 25)
  const urgencyScores = {
    'immediately': 25,
    'this-week': 22,
    'this-month': 18,
    'this-quarter': 12,
    'just-exploring': 5
  };
  score += urgencyScores[leadData.timelineUrgency] || 10;

  // Tried micro solutions (max 15) - shows they're serious
  if (leadData.microSolutionsTried) {
    score += 15;
  }

  // Has detailed problem description (max 15)
  if (leadData.problemDescription && leadData.problemDescription.length > 100) {
    score += 15;
  } else if (leadData.problemDescription && leadData.problemDescription.length > 50) {
    score += 10;
  } else if (leadData.problemDescription) {
    score += 5;
  }

  return Math.min(score, 100);
};

/**
 * Save conversation/messages for a lead
 */
export const saveConversation = async (leadId, messages, recommendations) => {
  try {
    const { data, error } = await supabase
      .from('conversations')
      .insert([{
        lead_id: leadId,
        messages: messages,
        recommendations: recommendations
      }])
      .select();

    if (error) throw error;
    return { success: true, data: data[0] };
  } catch (error) {
    console.error('Error saving conversation:', error);
    return { success: false, error: error.message };
  }
};

export default supabase;
