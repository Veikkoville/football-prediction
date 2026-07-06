/** Supabase-client (sama projekti kuin mobiili — yksi tili, premium kaikkialla).
 * Anon key on selainturvallinen; RLS rajaa luvut omaan riviin.
 */
import { createClient } from '@supabase/supabase-js';
import { SUPABASE_URL, SUPABASE_ANON_KEY } from './config';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
