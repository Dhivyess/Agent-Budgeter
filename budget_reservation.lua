-- Atomic 3-Tier Budget Reservation Script
-- KEYS[1]: Session Budget (budget:session:...)
-- KEYS[2]: Agent Budget (budget:agent:...)
-- KEYS[3]: Team Budget (budget:team:...)
-- ARGV[1]: Estimated cost
-- ARGV[2]: Session Limit
-- ARGV[3]: Agent Limit
-- ARGV[4]: Team Limit

local est_cost = tonumber(ARGV[1])
local sess_limit = tonumber(ARGV[2])
local agent_limit = tonumber(ARGV[3])
local team_limit = tonumber(ARGV[4])

local curr_sess = tonumber(redis.call('GET', KEYS[1]) or "0")
local curr_agent = tonumber(redis.call('GET', KEYS[2]) or "0")
local curr_team = tonumber(redis.call('GET', KEYS[3]) or "0")

if (curr_sess + est_cost) > sess_limit then
    return {0, "session", curr_sess, sess_limit}
elseif (curr_agent + est_cost) > agent_limit then
    return {0, "agent", curr_agent, agent_limit}
elseif (curr_team + est_cost) > team_limit then
    return {0, "team", curr_team, team_limit}
else
    local new_sess = redis.call('INCRBY', KEYS[1], est_cost)
    redis.call('INCRBY', KEYS[2], est_cost)
    redis.call('INCRBY', KEYS[3], est_cost)
    return {1, "approved", new_sess, sess_limit}
