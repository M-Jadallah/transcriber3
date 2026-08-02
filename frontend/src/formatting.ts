import { api, post } from './api';

export type Reasoning = 'low' | 'medium' | 'high' | 'xhigh';

export type FormattingSkill = {
  id: string;
  name: string;
  slug: string;
  description: string;
  sha256: string;
  is_enabled: boolean;
  created_at: string;
};

export type FormattingArtifact = {
  id: string;
  format: string;
  file_name: string;
  size_bytes: number;
};

export type FormattingJob = {
  id: string;
  source_job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  progress: number;
  skill_name_snapshot: string;
  model_snapshot: string;
  reasoning_snapshot: Reasoning;
  attempt_number: number;
  error_message?: string | null;
  output_preview?: string | null;
  created_at: string;
  completed_at?: string | null;
  artifacts?: FormattingArtifact[];
};

export type FormattingSettings = {
  enabled: boolean;
  default_model: string;
  default_reasoning: Reasoning;
  default_skill_id?: string | null;
  skills: FormattingSkill[];
};

export type OpenCodeAuthMethod = {
  type: 'oauth' | 'api';
  label: string;
  prompts?: Array<{
    key: string;
    type: string;
    label: string;
    placeholder?: string;
  }>;
};

export type OpenCodeProvider = {
  id?: string;
  name?: string;
  models?: Record<string, { id?: string; name?: string }>;
};

export type OpenCodeAuthStatus = {
  available: boolean;
  connected: boolean;
  version?: string;
  connected_providers: string[];
  auth_methods: Record<string, OpenCodeAuthMethod[]>;
  providers: OpenCodeProvider[];
  default_models?: Record<string, string>;
  error?: string;
};

export function startFormatting(
  sourceJobId: string,
  options: {
    skill_id?: string;
    model?: string;
    reasoning?: Reasoning;
  } = {},
) {
  return post<FormattingJob>('/formatting/jobs', {
    source_job_id: sourceJobId,
    ...options,
  });
}

export function getLatestFormatting(jobIds: string[]) {
  if (!jobIds.length) {
    return Promise.resolve({} as Record<string, FormattingJob>);
  }
  return api<Record<string, FormattingJob>>(
    `/formatting/jobs/latest?job_ids=${encodeURIComponent(jobIds.join(','))}`,
  );
}
