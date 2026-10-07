{ inputs, ... }:
{
  env.SPIKE_TEMPLATE_PATH = toString inputs."local-template";
}
