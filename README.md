# flux-multitenant-demo

Demo for using fluxcd to deploy multitenant apps with kube namespace separation.

A `ctrl.py` handles flux bootstrap, tenant creation etc. It's a simple demo that
doesn't bother to support private git repos, deploy keys etc, the point is the
multi-namespace kustomization resources not the flux install details.

This does *not* use the in-development fluxcd multi-tenant support, it works
with the current-at-time-of-writing fluxcd
[v0.41.0](https://github.com/fluxcd/flux2/releases/tag/v0.41.2)
or on [v2.0.0-rc.1](https://github.com/fluxcd/flux2/releases/tag/v2.0.0-rc.1).

Here's how it looks

```
$ ./ctrl.py tenant add --tenant-namespace tenant81 --tenant-name "anothertenant"
Tenant created. Run "flux get ks --namespace tenant81" for status

$ flux --namespace tenant81 get ks
NAME 	REVISION          	SUSPENDED	READY	MESSAGE                              
dummy	main@sha1:0a861c8e	False    	True 	Applied revision: main@sha1:0a861c8e	

$ flux --namespace tenant81 tree ks dummy                     
Kustomization/tenant81/dummy
└── Deployment/tenant81/dummy

$ kubectl --namespace tenant81 get deployment/dummy -oyaml | yq '.spec.template.spec.containers[].env'
- name: SUBST_LITERAL
  value: anothertenant
```

See [How It Works](#how-it-works) for details.

## Run the demo

[Install the `flux` CLI](https://fluxcd.io/flux/installation/#install-the-flux-cli).

Install [`pipenv`](https://pypi.org/project/pipenv/) if you don't have it
already; usually just `sudo apt install pipenv` or `brew install pipenv`.

Set up an empty kube cluster or one you're willing to sacrifice and ensure it
is your current default kube context. The simplest way is to install `kind` and
run `kind create cluster`.

Run the bootstrap script to deploy fluxcd on your cluster, pointing to this
repo.

```sh
pipenv sync
pipenv shell
./ctrl.py bootstrap
```

Now use the control script to create a tenant:

```sh
$ ./ctrl.py tenant add --tenant-namespace foo --tenant-name "sometenant"            
```

This will create a namespace `foo` with label `tenant-name=sometenant` and deploy a
flux `Kustomization` resource within it. The kustomization will reference the
`GitRepository` source to find the sources in `./kustomizations/per-tenant`
and deploy them, with variable subtitutions specific to the tenancy.

Get status with

```
$ flux get ks --namespace foo                         
NAME 	REVISION          	SUSPENDED	READY	MESSAGE                              
dummy	main@sha1:69e321ac	False    	True 	Applied revision: main@sha1:69e321ac

$ kubectl get deployment --namespace foo              
NAME    READY   UP-TO-DATE   AVAILABLE   AGE
dummy   1/1     1            1           4m16s

$ kubectl logs --namespace foo -l app.kubernetes.io/name=dummy 
This tenant name is "sometenant"
subst seems to have been applied ok
```

## Controller commands

### bootstrap

Install fluxcd into the kube cluster and create the flux GitRepository source

### tenant add

Create a new namespace, tenant-specific ConfigMap in the namespace, and flux Kustomization
resource to deploy the dummy app into that namespace.

Roughly equivalent to

```sh
kubectl create namespace tenant-namespace -l flux-multitenant-demo.ringerc.github.com/tenant-name=tenant-name

kubectl create configmap -n tenant-namespace \\
        --from-literal=PER_TENANT_SUBST='This tenant name is "tenant-name"' \\
        tenant-vars

# These steps for flux tenant are currently optional; it's what the script does, but
# does not appear to have the desired effect yet
flux create tenant foo --with-namespace foo --export > flux-tenant.yaml
kubectl label namespace \
  tenant-namespace kubernetes.io/metadata.name=baz,toolkit.fluxcd.io/tenant=tenant-namespace
kfilt --kind=ServiceAccount < flux-tenant.yaml | kubectl apply -f -
kfilt --kind=RoleBinding < flux-tenant.yaml | kubectl apply -f -

flux create ks dummy \
        --namespace tenant-namespace \
        --target-namespace=tenant-namespace \
        --source=GitRepository/default.flux-system \
        --prune \
        --path=./kustomizations/per-tenant \
        --export > flux-ks-manifest.yaml

yq -i '.spec.postBuild={
		"substitute":{
			"SUBST_LITERAL":"This tenant name is tenant-name"
		},
		"substituteFrom":[
			{"kind":"ConfigMap","name":"tenant-vars"}
		]
	}' flux-ks-manifest.yaml

kubectl apply -f flux-ks-manifest.yaml
```

### tenant list

List all tenant namespaces. Equivalent to

```sh
kubectl get namespace -l 'tenant-name'
```

### tenant delete

Delete a namespace containing a tenant app.

With `--tenant-namespace`, equivalent to:

```sh
kubectl delete namespace tenant-namespace
```

or with `--tenant-name`:

```sh
kubectl delete namespace -l tenant-name=foo
```

## How it works

Flux's controllers are installed into `flux-system`.

It is configured to look for flux `Kustomization` resources in all namespaces,
not just the `flux-system` namespace, using the `--watch-all-namespaces` flag
to `flux install`.

A flux `GitSource` named `default` is created in the `flux-system` namespace. This
resource watches this repo.

When a tenant is created, the `ctrl tenant add` command creates:

* a namespace `{{tenantns}}` for the tenant, with a `tenant-name={{tenantname}}` label
* a `ConfigMap` named `tenant-vars` in that namespace, with a single key
  `PER_TENANT_SUBST: This tenant name is "{{tenantname}}"`
* a `ServiceAccount` and `RoleBinding` giving the flux kustomize controller
  access to the namespace when applying Kustomization resources under that
  namespace
* a fluxcd `Kustomization` resource in that namespace that defines where to get the
  sources, how to transform them etc

The per-tenant flux Kustomization has:

* `sourceRef` that points to the `default` `GitRepository` in the `flux-sytem`
  namespace. You can refer to sources in other namespaces if desired, e.g.
  per-tenant sources.
* `path` pointing to `./kustomizations/per-tenant` - which is where the
  template kustomizations to apply live
* `targetNamespace` set to `{{tenantnamespace}}` so a tenant kustomization
  cannot create resources outside its namespace by mistake
* A `postBuild.substituteFrom` referencing `ConfigMap` `tenant-vars`
  and a `postBuild.substitute` literal of `SUBST_LITERAL={{tenantname}}`. These
  are applied as
  [flux kustomization substitutions](https://fluxcd.io/flux/components/kustomize/kustomization/#post-build-variable-substitution).
  Secrets are supported too. You should prefer using a configmap over using
  literals, I've only used one for illustration/demo purposes.

The flux source controller will pull and sync the repo, then the flux kustomize
controller will reconcile each flux `Kustomization` resource. It will do the
approximate equivalent of `kustomize build ./kustomizations/per-tenant` then
apply variable substitutions (a bit like if you `envsubst`'d the built manifests)
then apply the manifest to the target namespace.

That `kustomize build`-like step in the flux kustomize controller will read
[`kustomizations/per-tenant/kustomization.yaml`](./kustomizations/per-tenant/kustomization.yaml)
from the copy of the repo and pull in the
[`kustomizations/per-tenant/dummy_deployment.yaml`](./kustomizations/per-tenant/dummy_deployment.yaml)
manifest.

The substitutions step will replace the `${PER_TENANT_SUBST}` and any other
`${VAR_REFS}` in the manifest with values obtained from the tenant's
flux Kustomization postbuild substitutions.

The resulting `Pod` for tenant with namespace `foo` and name `sometenant` looks
like:

```
$ kubectl get pod -n foo -oyaml | yq -r '.items[].spec.containers[0]|{"command":.command, "args":.args, "env":.env}' 
command:
  - /bin/sh
args:
  - -c
  - echo 'This tenant name is "sometenant"'; if [ 'This tenant name is "sometenant"' = '$''{''PER_TENANT_SUBST''}' ]; then echo 1>&2 'no substitution applied?!'; exit 1; else echo 1>&2 'subst seems to have been applied ok'; env | grep SUBST; sleep inf; fi
env:
  - name: SUBST_LITERAL
    value: tenantname
```


### Sample manifests for a tenant

Given tenant namespace `foo` with tenant name `sometenant`

#### Created by `ctrl tenant add`

the `ctrl tenant add` command will deploy:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  labels:
    kubernetes.io/metadata.name: foo
    flux-multitenant-demo.ringerc.github.com/tenant-name: sometenant
  name: foo
spec: {}
```

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: tenant-vars
  namespace: foo
data:
  PER_TENANT_SUBST: This tenant name is "sometenant"
```

a `ServiceAccount` and `RoleBinding` that match what `flux create tenant` would do:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  labels:
    toolkit.fluxcd.io/tenant: tenant-namespace
  name: tenant-namespace
  namespace: tenant-namespace
```

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  labels:
    toolkit.fluxcd.io/tenant: tenant-namespace
  name: tenant-namespace-reconciler
  namespace: tenant-namespace
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: gotk:tenant-namespace:reconciler
- kind: ServiceAccount
  name: tenant-namespace
  namespace: tenant-namespace
```

and a `Kustomization` rsrc based on
[`tenant-flux-kustomization-template.yaml`](./tenant-flux-kustomization-template.yaml):

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1beta2
kind: Kustomization
metadata:
  name: dummy
  namespace: foo
spec:
  force: false
  interval: 5m
  path: ./kustomizations/per-tenant
  postBuild:
    substitute:
      SUBST_LITERAL: sometenant
    substituteFrom:
    - kind: ConfigMap
      name: tenant-vars
      optional: false
  prune: true
  sourceRef:
    kind: GitRepository
    name: default
    namespace: flux-system
  targetNamespace: foo
```

#### Created by flux kustomize controller

Then fluxcd will reconcile to deploy a templated version of
[`kustomizations/per-tenant/dummy_deployment.yaml`](./kustomizations/per-tenant/dummy_deployment.yaml):

```
apiVersion: apps/v1
kind: Deployment
metadata:
  labels:
    app.kubernetes.io/name: dummy
    kustomize.toolkit.fluxcd.io/name: dummy
    kustomize.toolkit.fluxcd.io/namespace: foo
  name: dummy
  namespace: foo
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/instance: dummy
  template:
    metadata:
      labels:
        app.kubernetes.io/instance: dummy
        app.kubernetes.io/name: dummy
    spec:
      containers:
      - args:
        - -c
        - echo 'This tenant name is "sometenant"'; if [ 'This tenant name is "sometenant"'
          = '$''{''PER_TENANT_SUBST''}' ]; then echo 1>&2 'no substitution applied?!';
          exit 1; else echo 1>&2 'subst seems to have been applied ok'; env | grep
          SUBST; sleep inf; fi
        command:
        - /bin/sh
        env:
        - name: SUBST_LITERAL
          value: sometenant
        image: alpine:latest
        name: dummy
```

and the `Deployment` will create an appropriate `Pod`.

## Integrating flux tenants for confinement and RBAC

This is WIP.

The [`flux create tenant` command](https://fluxcd.io/flux/cmd/flux_create_tenant/) is rather under-documented.

Its source and output shows it creates a labeled `Namespace`, a
`ServiceAccount` and a `RoleBinding`:

```sh
flux create tenant foo --with-namespace foo --export
```

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  labels:
    toolkit.fluxcd.io/tenant: foo
  name: foo

---
apiVersion: v1
kind: ServiceAccount
metadata:
  labels:
    toolkit.fluxcd.io/tenant: foo
  name: foo
  namespace: foo

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  labels:
    toolkit.fluxcd.io/tenant: foo
  name: foo-reconciler
  namespace: foo
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- apiGroup: rbac.authorization.k8s.io
  kind: User
  name: gotk:foo:reconciler
- kind: ServiceAccount
  name: foo
  namespace: foo
```

Looks like this is intended to confine what kustomizations can do within a namespace.

I've tried adding these to the demo, but presumably I then have to configure
the flux kustomize controller to have lower default privs. Currently if I
deploy

```yaml
flux create ks wrong-namespace --namespace baz --source=GitRepository/default.flux-system --prune --path=./kustomizations/wrong-namespace
```

then I still get a successful reconciliation

```
$ kubectl get configmap -n default wrong-namespace
NAME              DATA   AGE
wrong-namespace   1      9m51s
```
