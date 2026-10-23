"""Actual Git reachability checks for fixed candidates after report-only commits."""
import pathlib
import hashlib
import json
import subprocess
import tempfile
import unittest
from unittest import mock

import clean_run_build as build


class RevisionTests(unittest.TestCase):
    def test_sparse_reuse_requires_exact_new_namespace_revision_and_proven_hashes(self):
        row = dict(revision=build.NATIVE_REVISION,sha256=build.NATIVE_HASHES[0],bot_sha256=build.NATIVE_HASHES[1])
        proof = dict(game=dict(row),bots=dict(row))
        args = [build.NATIVE_R2,build.NATIVE_REVISION,'clean-idle150-audit-r1-20261022',proof]
        build.validate_sparse_reuse(*args)
        for index,value in ((0,'clean-idle150-audit-r1-20261022'),(0,'clean-other'),
                            (1,'0'*40),(2,'clean-other'),(3,None)):
            bad=list(args);bad[index]=value
            with self.assertRaises(ValueError):build.validate_sparse_reuse(*bad)
        for key in ('revision','sha256','bot_sha256'):
            wrong = dict(game=row,bots=row|{key:'0'*len(row[key])})
            with self.assertRaises(ValueError):build.validate_sparse_reuse(*args[:3],wrong)

    def test_real_sparse_checkout_complete_rust_blobs_and_boundary_before_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp);source=root/'source';source.mkdir()
            def git(*args):
                return subprocess.check_output(['git','-C',str(source),*args],text=True,stderr=subprocess.DEVNULL).strip()
            git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
            for name in ('rust/Cargo.toml','rust/Cargo.lock','rust/server/src/main.rs',
                         'rust/protocol/src/lib.rs','client/assets/large','docs/manual.md','AGENTS.md'):
                p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(name)
            git('add','.');git('commit','-qm','source');revision=git('rev-parse','HEAD')
            bundle=root/'source.bundle';git('bundle','create',str(bundle),'HEAD')
            destination=root/'sparse'
            command=build.checkout_command(str(source),str(destination),str(bundle),revision,True)
            self.assertLess(command.index('sparse-checkout set rust'),command.index('checkout --detach'))
            result=subprocess.run(['/bin/sh','-ec',command],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse((destination/'client').exists());self.assertFalse((destination/'docs').exists())
            def proof(rev=revision):
                return subprocess.run(['/bin/sh','-ec',build.sparse_source_proof_command(str(destination),rev)],capture_output=True,text=True)
            result=proof();self.assertEqual(result.returncode,0,result.stderr)
            row=json.loads(result.stdout)
            self.assertEqual(row['rust_file_count'],4);self.assertTrue(row['all_materialized_blobs_verified'])
            self.assertEqual(row['specification'],'/*\n!/*/\n/rust/\n')
            self.assertTrue(row['shared_object_alternates'])
            self.assertNotEqual(proof('0'*40).returncode,0)
            f=destination/'rust/Cargo.lock';f.write_text('wrong contents')
            self.assertNotEqual(proof().returncode,0)
            f.write_text('rust/Cargo.lock');(destination/'client').mkdir()
            self.assertNotEqual(proof().returncode,0)
            ordinary=build.checkout_command(str(source),str(root/'full'),str(bundle),revision)
            self.assertNotIn('sparse-checkout',ordinary)

    def test_prior_proof_requires_exact_both_host_revision_path_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            directory = root/'clean-fixture-build'
            directory.mkdir()
            row = dict(revision='a'*40, path='/home/deploy/omega-clean-fixture',
                       sha256='b'*64,bot_sha256='c'*64)
            proof = dict(game=row,bots=dict(row))
            file = directory/'build-proof.json'
            file.write_text(json.dumps(proof))
            self.assertEqual(build.load_reuse_proof('clean-fixture','a'*40,root),proof)
            for key, value in (('revision','d'*40),('path','/tmp/arbitrary'),
                               ('sha256','e'*64),('bot_sha256','short')):
                file.write_text(json.dumps(dict(game=row,bots=row|{key:value})))
                with self.assertRaises(ValueError):
                    build.load_reuse_proof('clean-fixture','a'*40,root)
            with self.assertRaises(ValueError):
                build.load_reuse_proof('../escape','a'*40,root)

    def test_real_copy_preserves_source_and_refuses_dirty_symlink_or_wrong_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            source = root/'source with spaces'
            source.mkdir()
            for argv in (['init','-q'],['config','user.name','Fixture'],
                         ['config','user.email','fixture@example.invalid']):
                subprocess.run(['git','-C',str(source),*argv],check=True)
            (source/'.gitignore').write_text('/rust/target/\n')
            subprocess.run(['git','-C',str(source),'add','.gitignore'],check=True)
            subprocess.run(['git','-C',str(source),'commit','-qm','fixture'],check=True)
            rev = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
            binary_dir = source/'rust/target/release'
            binary_dir.mkdir(parents=True)
            binaries = [binary_dir/name for name in ('omega-server','omega-load-test')]
            for binary in binaries:
                binary.write_bytes(binary.name.encode())
                binary.chmod(0o755)
            hashes = [hashlib.sha256(binary.read_bytes()).hexdigest() for binary in binaries]

            def execute(label, digests=hashes):
                destination = root/label
                # Exercise the real shell and file copies on macOS too; only
                # GNU cp's optional reflink flag is removed by this wrapper.
                script = 'set -e; cp() { command cp "$2" "$3"; }; '
                script += build.reuse_binaries_command(str(source),str(destination),rev,*digests)
                result = subprocess.run(['/bin/sh','-c',script],capture_output=True,text=True)
                return destination,result

            destination,result = execute('fresh')
            self.assertEqual(result.returncode,0,result.stderr)
            for binary, digest in zip(binaries,hashes):
                copied = destination/'rust/target/release'/binary.name
                self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(),digest)
                self.assertFalse(copied.is_symlink())
                self.assertNotEqual(copied.stat().st_ino,binary.stat().st_ino)
                self.assertEqual(copied.stat().st_mode & 0o777,0o755)
            self.assertNotEqual(execute('fresh')[1].returncode,0)
            dangling=root/'dangling-copy/rust/target/release'
            dangling.mkdir(parents=True)
            dangling.joinpath('omega-server').symlink_to(root/'must-not-be-created')
            self.assertNotEqual(execute('dangling-copy')[1].returncode,0)
            self.assertFalse((root/'must-not-be-created').exists())
            self.assertNotEqual(execute('wrong-hash',['0'*64,hashes[1]])[1].returncode,0)
            (source/'dirty').write_text('dirty')
            self.assertNotEqual(execute('dirty-copy')[1].returncode,0)
            (source/'dirty').unlink()
            saved = root/'saved'
            binaries[0].rename(saved)
            binaries[0].symlink_to(saved)
            self.assertNotEqual(execute('symlink-copy')[1].returncode,0)

    def test_exact_candidate_survives_head_advance_and_bundle_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            repo = root/'source'
            repo.mkdir()

            def git(*args):
                return subprocess.check_output(['git', *args], cwd=repo, text=True,
                                               stderr=subprocess.DEVNULL).strip()

            git('init', '-q')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')

            def commit(value):
                (repo/'source').write_text(value)
                git('add', 'source')
                git('commit', '-qm', value)
                return git('rev-parse', 'HEAD')

            base = commit('base')
            candidate = commit('candidate')
            commit('report-only')
            with mock.patch.object(build, 'BASE_REVISION', base):
                self.assertEqual(build.validate_revision(candidate, repo), candidate)
                bundle = root/'candidate.bundle'
                git('bundle', 'create', str(bundle), base+'..HEAD')
                git('bundle', 'verify', str(bundle))
                clone = root/'clone'
                subprocess.run(['git', 'clone', '-q', str(repo), str(clone)], check=True)
                subprocess.run(['git', '-C', str(clone), 'fetch', '-q', str(bundle), 'HEAD'], check=True)
                subprocess.run(['git', '-C', str(clone), 'cat-file', '-e', candidate+'^{commit}'], check=True)
                subprocess.run(['git', '-C', str(clone), 'merge-base', '--is-ancestor', candidate, 'FETCH_HEAD'], check=True)
                with self.assertRaises(ValueError):
                    build.validate_revision(base, repo)
                git('tag', '-a', '-m', 'tag', 'candidate-tag', candidate)
                with self.assertRaises(ValueError):
                    build.validate_revision(git('rev-parse', 'candidate-tag'), repo)
                git('checkout', '-q', '--detach', base)
                orphan = commit('unreachable-from-final-head')
                git('checkout', '-q', '--detach', candidate)
                with self.assertRaises(subprocess.CalledProcessError):
                    build.validate_revision(orphan, repo)
            with self.assertRaises(ValueError):
                build.validate_revision('HEAD', repo)
            with self.assertRaises(subprocess.CalledProcessError):
                build.validate_revision('0'*40, repo)


if __name__ == '__main__':
    unittest.main()
