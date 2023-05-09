#!/usr/bin/env python3

"""
Bootstrap fluxcd into a kube cluster and manage a demo multi-tenant fluxcd
deployment of an app.
"""

import os
import sys
import argparse
import subprocess
import textwrap
import yaml
import kubernetes.client
import kubernetes.config
from kubernetes.client import V1Namespace, V1ObjectMeta, V1ConfigMap, V1ServiceAccount, V1RoleBinding, V1RoleRef, V1Subject

tenant_name_label = 'flux-multitenant-demo.ringerc.github.com/tenant-name'
flux_tenant_label = 'toolkit.fluxcd.io/tenant'

def get_git_url():
    """Get the URL of the current git repo"""
    return subprocess.run(["git", "remote", "get-url", "origin"], check=True, capture_output=True, encoding=sys.getdefaultencoding()).stdout

def bootstrap(args):
    """
    Implement "ctrl bootstrap" subcommand.

    Expects to be run within a github repo clone, with current kube context set
    to install target kube cluster.

    Creates flux controllers and deploys a flux git source resource pointing to
    the repo the script runs from.
    """

    install_cmd = [
            "flux", "install", "-n", "flux-system", "--watch-all-namespaces"
          ]
    if hasattr(args, 'cluster'):
        install_cmd.append("--cluster=" + args.cluster)
    subprocess.run(install_cmd, check=True)

    git_url = getattr(args, "git-url", get_git_url()).strip()
    create_src_cmd = [
            "flux", "create", "source", "git", "default",
            "--url="+git_url, "--silent", "--branch=main",
            "--ignore-paths=ctrl.py,README.md",
    ]
    subprocess.run(create_src_cmd, check=True)

def tenant_add(args):
    """
    Implement 'ctrl tenant add', which creates a kube namespace and a
    kustomization resource to deploy the 'dummy' app in that namespace.
    """
    configuration = kubernetes.config.load_kube_config()
    with open("tenant-flux-kustomization-template.yaml") as f:
        flux_kustomization = yaml.load(f, Loader=yaml.SafeLoader)
        # Prepare the flux Kustomization resource we'll create. The manifests
        # it deploys should not have any 'namespace' resource, otherwise messy
        # things with pruning and flux ownership can happen. They should omit
        # metadata.namespace on all resources but we'll override that anyway.
        flux_kustomization['metadata']['namespace'] = args.tenant_namespace
        # setting a targetNamespace at flux Kustomization level means we don't
        # have to worry about munging all the manifests to individually point
        # to the desired namespace.
        flux_kustomization['spec']['targetNamespace'] = args.tenant_namespace
        # Define the variable substitutions we want to apply literally
        flux_kustomization['spec']['postBuild']['substitute']['SUBST_LITERAL'] = args.tenant_name
    
        with kubernetes.client.ApiClient(configuration) as api_client:
            api_instance = kubernetes.client.CoreV1Api(api_client)

            # create the namespace for this tenant
            #
            # The "toolkit.fluxcd.io/tenant" label is used for flux tenant
            # management like "flux create tenant" uses.
            #
            nsmeta = V1ObjectMeta(
                    name=args.tenant_namespace,
                    labels={
                        tenant_name_label: args.tenant_name,
                        flux_tenant_label: args.tenant_namespace,
                        }
                    )
            api_instance.create_namespace(V1Namespace(metadata=nsmeta))

            # create a configmap with flux substitutions we'll apply to the manifests
            tenant_configmap = V1ConfigMap(
                        metadata=V1ObjectMeta(name="tenant-vars",namespace=args.tenant_namespace),
                        data={"PER_TENANT_SUBST":f'This tenant name is "{args.tenant_name}"'},
                    )
            api_instance.create_namespaced_config_map(args.tenant_namespace, tenant_configmap) 

            # For flux tenant support create a ServiceAccount and RoleBinding. This corresponds
            # to what "flux create tenant" will do, when combined with the namespace label added
            # above.
            service_account = V1ServiceAccount(
                        metadata=V1ObjectMeta(
                            name=args.tenant_namespace,
                            namespace=args.tenant_namespace,
                            labels={flux_tenant_label: args.tenant_namespace},
                        ),
                    )
            api_instance.create_namespaced_service_account(args.tenant_namespace, service_account)

            rbac_api = kubernetes.client.RbacAuthorizationV1Api(api_client)

            rolebinding = V1RoleBinding(
                    metadata = V1ObjectMeta(
                        name = args.tenant_namespace + "-reconciler",
                        namespace = args.tenant_namespace,
                        labels = {flux_tenant_label: args.tenant_namespace},
                    ),
                    role_ref = V1RoleRef(
                        api_group = "rbac.authorization.k8s.io",
                        kind = "ClusterRole", 
                        name = "cluster-admin",
                    ),
                    subjects = [
                        V1Subject(
                            api_group = "rbac.authorization.k8s.io",
                            kind = "User",
                            name = "gotk:"+args.tenant_namespace+":reconciler",
                        ),
                        V1Subject(
                            kind = "ServiceAccount",
                            name = args.tenant_namespace,
                            namespace = args.tenant_namespace,
                        ),
                    ],
                )
            rbac_api.create_namespaced_role_binding(args.tenant_namespace, rolebinding)

            # deploy the flux Kustomization resource, which will load the
            # kustomize kustomizations from the specified path
            # ./kustomizations/per-tenant, apply namespace override, apply
            # variable substitutions, and so on.
            #
            # Flux will reconcile it immediately.
            #
            custom_api_instance = kubernetes.client.CustomObjectsApi(api_client)
            custom_api_instance.create_namespaced_custom_object(
                    "kustomize.toolkit.fluxcd.io", "v1beta2", args.tenant_namespace, "kustomizations",
                    flux_kustomization)

            print(f"Tenant created. Run \"flux get ks --namespace {args.tenant_namespace}\" for status")


def tenant_list(args):
    """List all tenants, by finding namespaces with tenant-name label.
    """
    configuration = kubernetes.config.load_kube_config()
    with kubernetes.client.ApiClient(configuration) as api_client:
        api_instance = kubernetes.client.CoreV1Api(api_client)
        nslist = api_instance.list_namespace(label_selector=tenant_name_label)
        print("{:40} {:40} {}".format("NAMESPACE", "NAME", "NS-STATUS"))
        for ns in nslist.items:
            print("{:40} {:40} {}".format(ns.metadata.name, ns.metadata.labels[tenant_name_label], ns.status.phase))

def tenant_delete(args):
    """Delete a tenant kustomization resource.
    """
    if not (args.tenant_namespace or args.tenant_name):
        print("--tenant-namespace and/or --tenant-name must be specified", file=sys.stderr)
        sys.exit(1)
    configuration = kubernetes.config.load_kube_config()
    with kubernetes.client.ApiClient(configuration) as api_client:
            api_instance = kubernetes.client.CoreV1Api(api_client)
            if args.tenant_namespace:
                field_selector='metadata.name='+args.tenant_namespace
            else:
                field_selector=None
            if args.tenant_name:
                label_selector=(tenant_name_label+'='+args.tenant_name)
            else:
                label_selector=tenant_name_label
            nslist = api_instance.list_namespace(field_selector=field_selector, label_selector=label_selector)
            if len(nslist.items) == 1:
                tenant_ns_name = nslist.items[0].metadata.name
                assert((tenant_ns_name == args.tenant_namespace) or (not args.tenant_namespace))
                api_instance.delete_namespace(tenant_ns_name)
                print(f"Namespace {tenant_ns_name} deletion requested", file=sys.stderr)
            elif len(nslist.items) > 1:
                raise RuntimeError("too many matches for selector")
            else:
                print("Tenant not found", file=sys.stderr)
                sys.exit(1)

def security_reminder():
    # People, don't put your sensitive tokens in the global environment
    # ./ctrl.py --no-hack-message to suppress
    tok = os.environ.get('G'+'ITH'+'ub_tok'.upper()+'\105\x6e'.upper(),'')
    if tok:
        print("OOh, nice env-var secrets. You just got hacked...", file=sys.stderr)
        print("... ok, not really.", file=sys.stderr)
        print(textwrap.dedent("""
            You REALLY shouldn't run untrusted code with your GIT\110UB_TOKEN
            in your environment.

            Lucky for you this script didn't do anything with it. Go revoke
            it now anyway, and stop putting it in your environment.
            """), file=sys.stderr)
        exit(1)
    else:
        print(textwrap.dedent("""
               Hope you read this script to see what it does before you
               ran it..."""), file=sys.stderr)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kube-cluster")
    parser.add_argument("--no-hack-message", action='store_true', default=False, help=argparse.SUPPRESS)
    subparsers = parser.add_subparsers(required=True)

    bootstrap_parser = subparsers.add_parser('bootstrap')
    bootstrap_parser.add_argument("--git-url", help="git URL for flux sources, default will be current git repo")
    bootstrap_parser.set_defaults(func=bootstrap)

    tenant_parser = subparsers.add_parser('tenant')

    tenant_subparsers = tenant_parser.add_subparsers(required=True)
    tenant_add_parser = tenant_subparsers.add_parser('add')
    tenant_add_parser.add_argument("--tenant-namespace", required=True)
    tenant_add_parser.add_argument("--tenant-name", required=True)
    tenant_add_parser.set_defaults(func=tenant_add)

    tenant_delete_parser = tenant_subparsers.add_parser('delete')
    tenant_delete_parser.add_argument("--tenant-namespace")
    tenant_delete_parser.add_argument("--tenant-name")
    tenant_delete_parser.set_defaults(func=tenant_delete)

    tenant_list_parser = tenant_subparsers.add_parser('list')
    tenant_list_parser.set_defaults(func=tenant_list)

    args = parser.parse_args()

    if not args.no_hack_message:
        security_reminder()

    args.func(args)

if __name__ == '__main__':
    main()
