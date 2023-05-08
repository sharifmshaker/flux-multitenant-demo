These kustomize resources are applied to each created tenant, parameterised
with config vars specific to the tenant.

The Kustomization here is a
[Kustomize `Kustomization` resource](https://kustomize.io/),
not a
[flux kustomize controller `Kustomization` resource](https://fluxcd.io/flux/components/kustomize/kustomization/).

It defines a `Deployment` called `dummy` that instantiates one replica. It
expects a textual substitution of `${PER_TENANT_SUBST}` to be made after
`kustomize build` and before the manifests are applied.

The flux resources that manage the deployment of these get created by the
`ctrl` script. It
[configures flux Kustomize substitutions](https://fluxcd.io/flux/components/kustomize/kustomization/#post-build-variable-substitution)
to apply the `${PER_TENANT_SUBST}` subst. The effect is broadly similar to
running:

    kustomize build . | PER_TENANT_SUBST=newvalue envsubst
