# flux-multitenant-demo

Demo for using fluxcd to deploy multitenant apps with kube namespace separation.

A `ctrl.py` handles flux bootstrap, tenant creation etc. It's a simple demo that
doesn't bother to support private git repos, deploy keys etc, the point is the
multi-namespace kustomization resources not the flux install details.

This does *not* use the in-development fluxcd multi-tenant support, it works
with the current-at-time-of-writing fluxcd
[v0.41.0](https://github.com/fluxcd/flux2/releases/tag/v0.41.2)
or on [v2.0.0-rc.1](https://github.com/fluxcd/flux2/releases/tag/v2.0.0-rc.1).

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

### tenant list

List all tenant namespaces

### tenant delete

Delete a namespace containing a tenant app
